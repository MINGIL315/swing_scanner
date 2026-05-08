"""KIS 공개 KOSPI 종목 마스터 파일 다운로드/파싱.

KIS Developers 가 매일 공개하는 정적 zip 파일을 받아 Pandas DataFrame 으로
반환한다. **인증이 필요 없으며** KIS API 호출 한도와도 무관하다.

URL: ``https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip``

KOSPI 시장 전체 종목 (코스피200 외 일반 코스피 포함) 의 마스터 정보를 담고 있으며
``KOSPI200섹터업종`` 컬럼으로 KOSPI200 구성종목을 식별할 수 있다.

주요 함수:
    download_kospi_master_mst    : zip 다운로드 + 해제 → ``.mst`` 파일 경로
    parse_kospi_master_dataframe : ``.mst`` fixed-width 파일 → DataFrame
    fetch_kospi200_constituents  : 위 두 단계를 합쳐 KOSPI200 구성종목만 반환

파싱 사양은 KIS 공식 샘플(``open-trading-api/stocks_info/kis_kospi_code_mst.py``)
을 그대로 따른다.
"""
from __future__ import annotations

import tempfile
import time
import zipfile
from pathlib import Path

import httpx
import pandas as pd
from loguru import logger

from scanner.config import (
    FETCH_RETRY_BACKOFF_BASE,
    FETCH_RETRY_MAX,
    FETCH_TIMEOUT_SECONDS,
)


KOSPI_MASTER_ZIP_URL = (
    "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
)
_MST_FILENAME = "kospi_code.mst"
# part2 fixed-width 영역 길이 (실제 데이터 227 byte + 줄바꿈 1 byte = 228).
# read_fwf 는 widths 합(227) 만큼만 읽고 줄바꿈은 자동 무시한다.
_PART2_LEN = 228


# part2 (228 bytes fixed-width) 의 컬럼 width — KIS 공식 샘플 기준
_PART2_WIDTHS: list[int] = [
    2, 1, 4, 4, 4,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 9, 5, 5, 1,
    1, 1, 2, 1, 1,
    1, 2, 2, 2, 3,
    1, 3, 12, 12, 8,
    15, 21, 2, 7, 1,
    1, 1, 1, 1, 9,
    9, 9, 5, 9, 8,
    9, 3, 1, 1, 1,
]


_PART2_COLS: list[str] = [
    "그룹코드", "시가총액규모", "지수업종대분류", "지수업종중분류", "지수업종소분류",
    "제조업", "저유동성", "지배구조지수종목", "KOSPI200섹터업종", "KOSPI100",
    "KOSPI50", "KRX", "ETP", "ELW발행", "KRX100",
    "KRX자동차", "KRX반도체", "KRX바이오", "KRX은행", "SPAC",
    "KRX에너지화학", "KRX철강", "단기과열", "KRX미디어통신", "KRX건설",
    "Non1", "KRX증권", "KRX선박", "KRX섹터_보험", "KRX섹터_운송",
    "SRI", "기준가", "매매수량단위", "시간외수량단위", "거래정지",
    "정리매매", "관리종목", "시장경고", "경고예고", "불성실공시",
    "우회상장", "락구분", "액면변경", "증자구분", "증거금비율",
    "신용가능", "신용기간", "전일거래량", "액면가", "상장일자",
    "상장주수", "자본금", "결산월", "공모가", "우선주",
    "공매도과열", "이상급등", "KRX300", "KOSPI", "매출액",
    "영업이익", "경상이익", "당기순이익", "ROE", "기준년월",
    "시가총액", "그룹사코드", "회사신용한도초과", "담보대출가능", "대주가능",
]


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------


def download_kospi_master_mst(target_dir: Path) -> Path:
    """KIS 공개 KOSPI 마스터 zip 을 다운로드 + 해제하여 ``.mst`` 경로를 반환한다.

    재시도(``FETCH_RETRY_MAX``) + exponential backoff 를 적용한다.

    Args:
        target_dir: zip 저장 + 해제 대상 디렉토리.

    Returns:
        해제된 ``kospi_code.mst`` 파일 경로.

    Raises:
        httpx.HTTPError : 모든 재시도 실패 시 마지막 예외.
        RuntimeError    : zip 안에 ``kospi_code.mst`` 가 없는 경우.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / "kospi_code.zip"

    logger.info("KIS KOSPI 마스터 다운로드 시작: {}", KOSPI_MASTER_ZIP_URL)

    last_exc: Exception | None = None
    for attempt in range(FETCH_RETRY_MAX):
        try:
            with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS) as client:
                response = client.get(KOSPI_MASTER_ZIP_URL)
                response.raise_for_status()
                zip_path.write_bytes(response.content)
            last_exc = None
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "KOSPI 마스터 다운로드 실패 (attempt {}/{}): {}",
                attempt + 1, FETCH_RETRY_MAX, exc,
            )
            if attempt < FETCH_RETRY_MAX - 1:
                time.sleep(FETCH_RETRY_BACKOFF_BASE ** (attempt + 1))

    if last_exc is not None:
        raise last_exc

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target_dir)

    mst_path = target_dir / _MST_FILENAME
    if not mst_path.exists():
        raise RuntimeError(
            f"{_MST_FILENAME} 가 zip 아카이브에 없습니다: {zip_path}"
        )

    zip_path.unlink(missing_ok=True)
    logger.info("KOSPI 마스터 해제 완료: {}", mst_path)
    return mst_path


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------


def parse_kospi_master_dataframe(mst_path: Path) -> pd.DataFrame:
    """``.mst`` fixed-width 파일을 파싱해 마스터 DataFrame 을 반환한다.

    각 줄을 두 부분으로 분리:
        - 헤더(가변 길이): 단축코드(9) + 표준코드(12) + 한글명(나머지)
        - 본문(고정 228 bytes): 70개 fixed-width 컬럼 (``_PART2_COLS``)

    인코딩은 ``cp949`` (KIS 발행 형식 그대로).

    Args:
        mst_path: 해제된 ``kospi_code.mst`` 파일.

    Returns:
        모든 KOSPI 종목의 마스터 DataFrame.
        ``단축코드`` / ``한글명`` / ``KOSPI200섹터업종`` 등 73개 컬럼 포함.
    """
    part1_records: list[dict[str, str]] = []
    part2_lines: list[str] = []

    with open(mst_path, mode="r", encoding="cp949") as f:
        for line in f:
            head = line[: len(line) - _PART2_LEN]
            tail = line[-_PART2_LEN:]

            part1_records.append({
                "단축코드": head[0:9].rstrip(),
                "표준코드": head[9:21].rstrip(),
                "한글명": head[21:].strip(),
            })
            part2_lines.append(tail)

    df1 = pd.DataFrame(part1_records)

    # part2 는 fixed-width — 임시 파일로 적어 ``pd.read_fwf`` 에 위임
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="cp949", suffix=".tmp", delete=False
    ) as tf:
        tf.writelines(part2_lines)
        tmp_part2 = Path(tf.name)
    try:
        df2 = pd.read_fwf(
            tmp_part2,
            widths=_PART2_WIDTHS,
            names=_PART2_COLS,
            encoding="cp949",
        )
    finally:
        tmp_part2.unlink(missing_ok=True)

    return pd.merge(df1, df2, how="outer", left_index=True, right_index=True)


# ---------------------------------------------------------------------------
# 공개 API — KOSPI200 구성종목 추출
# ---------------------------------------------------------------------------


def fetch_kospi200_constituents() -> pd.DataFrame:
    """KIS 마스터를 다운로드/파싱하여 KOSPI200 구성종목만 반환한다.

    멤버십은 ``KOSPI200섹터업종`` 컬럼이 비어있지 않은 행으로 판정한다.

    Returns:
        columns = [ticker, name, sector]
            - ``ticker`` : 6자리 단축코드 (str)
            - ``name``   : 한글명
            - ``sector`` : KOSPI200섹터업종 코드/이름

    Raises:
        httpx.HTTPError / RuntimeError : 다운로드 또는 파일 부재 시.
    """
    with tempfile.TemporaryDirectory(prefix="kis_kospi_master_") as td:
        td_path = Path(td)
        mst_path = download_kospi_master_mst(td_path)
        df = parse_kospi_master_dataframe(mst_path)

    sector = df["KOSPI200섹터업종"].astype(str).str.strip()
    is_kospi200 = sector.notna() & (sector != "") & (sector.str.lower() != "nan")
    constituents = df[is_kospi200].copy()

    result = pd.DataFrame({
        "ticker": constituents["단축코드"].astype(str).str.strip(),
        "name": constituents["한글명"].astype(str).str.strip(),
        "sector": sector[is_kospi200].values,
    })

    logger.info("KOSPI200 구성종목 {}종목 추출", len(result))
    return result.reset_index(drop=True)
