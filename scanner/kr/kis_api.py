"""KIS(한국투자증권) OpenAPI 클라이언트.

토큰은 24h 유효, 발급은 1시간당 1회 제한 → 파일 캐싱 필수.
모든 시세조회는 ``KIS_RATE_LIMIT_SECONDS`` 간격을 두고 호출하며
실패 시 ``FETCH_RETRY_MAX`` 회 exponential backoff 재시도한다.

주요 함수:
    get_access_token      : OAuth access_token 발급/파일 캐시
    fetch_daily_chart     : 일/주/월봉 (TR FHKST03010100, 자동 페이징)
    fetch_financial_ratio : 연간 재무비율 (TR FHKST66430300)
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
from loguru import logger

from scanner.config import (
    FETCH_RETRY_BACKOFF_BASE,
    FETCH_RETRY_MAX,
    FETCH_TIMEOUT_SECONDS,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_BASE_URL,
    KIS_DAILY_CHUNK_DAYS,
    KIS_RATE_LIMIT_SECONDS,
    KIS_TOKEN_CACHE_PATH,
)


# ---------------------------------------------------------------------------
# 토큰 캐시
# ---------------------------------------------------------------------------

_TOKEN_LOCK = threading.Lock()
# 만료 임박 판정 여유 시간 — 만료 N분 전이면 재발급
_TOKEN_REFRESH_MARGIN = timedelta(minutes=10)


def _load_cached_token() -> dict[str, Any] | None:
    """파일에서 캐시된 토큰을 로드한다. 없거나 손상되면 None."""
    if not KIS_TOKEN_CACHE_PATH.exists():
        return None
    try:
        raw = json.loads(KIS_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        return {
            "access_token": raw["access_token"],
            "expires_at": datetime.fromisoformat(raw["expires_at"]),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("KIS 토큰 캐시 로드 실패: {}", exc)
        return None


def _save_cached_token(access_token: str, expires_at: datetime) -> None:
    """토큰을 파일에 저장한다."""
    KIS_TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    KIS_TOKEN_CACHE_PATH.write_text(
        json.dumps(
            {
                "access_token": access_token,
                "expires_at": expires_at.isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def get_access_token(force_refresh: bool = False) -> str:
    """KIS access_token 을 반환한다 (24h 유효, 파일 캐시).

    Args:
        force_refresh: True 면 캐시 무시하고 재발급.

    Returns:
        Bearer 토큰 문자열.

    Raises:
        RuntimeError: KIS_APP_KEY/SECRET 미설정 또는 발급 실패.
    """
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 이 .env 에 설정되지 않았습니다.")

    with _TOKEN_LOCK:
        if not force_refresh:
            cached = _load_cached_token()
            if cached and cached["expires_at"] > datetime.now() + _TOKEN_REFRESH_MARGIN:
                return cached["access_token"]

        logger.info("KIS access_token 발급 요청")
        response = httpx.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
            },
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()

        access_token: str = data["access_token"]
        expires_in: int = int(data.get("expires_in", 86400))
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        _save_cached_token(access_token, expires_at)
        logger.info("KIS access_token 발급 완료 (만료: {})", expires_at)
        return access_token


# ---------------------------------------------------------------------------
# 공통 HTTP 호출 (재시도 + rate limit + 토큰 자동 첨부)
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    """KIS 응답 문자열을 float 로 안전 변환한다.

    None / 빈 문자열 / "-" / 변환 실패 시 None 반환.
    """
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _request(
    method: str,
    path: str,
    *,
    tr_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """KIS API 공통 호출 (인증 + 재시도 + rate limit).

    Args:
        method : HTTP 메서드 ("GET" / "POST").
        path   : KIS_BASE_URL 기준 path.
        tr_id  : KIS TR ID.
        params : 쿼리 파라미터.

    Returns:
        JSON 응답 dict.

    Raises:
        httpx.HTTPError       : HTTP 통신 실패.
        RuntimeError          : KIS rt_cd != "0" (비즈니스 에러).
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
    }
    url = f"{KIS_BASE_URL}{path}"

    last_exc: Exception | None = None
    for attempt in range(FETCH_RETRY_MAX):
        try:
            time.sleep(KIS_RATE_LIMIT_SECONDS)
            response = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            rt_cd = str(data.get("rt_cd", ""))
            if rt_cd != "0":
                raise RuntimeError(
                    f"KIS API 오류 tr_id={tr_id} "
                    f"rt_cd={rt_cd} msg={data.get('msg1', '')}"
                )

            return data
        except (httpx.HTTPError, RuntimeError) as exc:
            last_exc = exc
            logger.warning(
                "KIS 호출 실패 (attempt {}/{}) tr_id={}: {}",
                attempt + 1,
                FETCH_RETRY_MAX,
                tr_id,
                exc,
            )
            if attempt < FETCH_RETRY_MAX - 1:
                time.sleep(FETCH_RETRY_BACKOFF_BASE ** (attempt + 1))

    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# 일/주/월봉 차트 (TR FHKST03010100)
# ---------------------------------------------------------------------------

_DAILY_CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_DAILY_CHART_TR = "FHKST03010100"


def _fetch_daily_chunk(
    ticker: str,
    start: date,
    end: date,
    period_div_code: str,
    adjusted_price: bool,
) -> pd.DataFrame:
    """100일 이내 단일 청크의 일/주/월봉을 반환한다."""
    data = _request(
        "GET",
        _DAILY_CHART_PATH,
        tr_id=_DAILY_CHART_TR,
        params={
            "FID_COND_MRKT_DIV_CODE": "J",          # J: KRX
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": period_div_code,  # D / W / M / Y
            "FID_ORG_ADJ_PRC": "0" if adjusted_price else "1",  # 0: 수정주가
        },
    )

    output2: list[dict[str, Any]] = data.get("output2", []) or []
    rows: list[dict[str, Any]] = []
    for item in output2:
        bsop_date = item.get("stck_bsop_date")
        if not bsop_date:
            continue
        try:
            row_date = datetime.strptime(bsop_date, "%Y%m%d").date()
        except ValueError:
            continue
        rows.append(
            {
                "ticker": ticker,
                "date": row_date,
                "open": _safe_float(item.get("stck_oprc")),
                "high": _safe_float(item.get("stck_hgpr")),
                "low": _safe_float(item.get("stck_lwpr")),
                "close": _safe_float(item.get("stck_clpr")),
                "volume": _safe_float(item.get("acml_vol")),
                "value": _safe_float(item.get("acml_tr_pbmn")),
            }
        )
    return pd.DataFrame(rows)


def fetch_daily_chart(
    ticker: str,
    start: date,
    end: date,
    period_div_code: str = "D",
    adjusted_price: bool = True,
) -> pd.DataFrame:
    """KIS 기간별 시세 (일/주/월/년봉) 를 조회한다.

    KIS API 는 한 번 호출에 약 100영업일치만 반환하므로
    ``KIS_DAILY_CHUNK_DAYS`` 단위로 분할 호출 후 합친다.

    Args:
        ticker          : 6자리 종목코드 (예: "005930").
        start           : 조회 시작일.
        end             : 조회 종료일.
        period_div_code : "D"(일) / "W"(주) / "M"(월) / "Y"(년).
        adjusted_price  : True 면 수정주가 적용.

    Returns:
        columns = [ticker, date, open, high, low, close, volume, value]
        실패/빈 결과 시 빈 DataFrame.
    """
    if start > end:
        return pd.DataFrame()

    # 청크 1개라도 실패하면 raise — 종목 전체 실패로 처리되어 다음 실행 시 재시도.
    # 부분 데이터 (중간 100일 누락) 가 DB 에 들어가는 것을 방지.
    chunks: list[pd.DataFrame] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(
            chunk_start + timedelta(days=KIS_DAILY_CHUNK_DAYS - 1),
            end,
        )
        df = _fetch_daily_chunk(
            ticker, chunk_start, chunk_end, period_div_code, adjusted_price
        )
        if not df.empty:
            chunks.append(df)
        chunk_start = chunk_end + timedelta(days=1)

    if not chunks:
        logger.warning("KIS 일봉 빈 결과: {} ({} ~ {})", ticker, start, end)
        return pd.DataFrame()

    combined = pd.concat(chunks, ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["ticker", "date"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    return combined


# ---------------------------------------------------------------------------
# 재무비율 (TR FHKST66430300)
# ---------------------------------------------------------------------------

_FINANCIAL_RATIO_PATH = "/uapi/domestic-stock/v1/finance/financial-ratio"
_FINANCIAL_RATIO_TR = "FHKST66430300"


def fetch_financial_ratio(ticker: str, annual: bool = True) -> pd.DataFrame:
    """KIS 재무비율의 최신 결산 1행에서 부채비율 + ROE 를 반환한다.

    KIS API ``FHKST66430300`` 응답 필드 중 분석에 사용되는 두 항목만 추출한다:
        - ``lblt_rate`` → ``debt_ratio`` (부채비율, %)
        - ``roe_val``   → ``roe``        (자기자본수익률, %)

    PER/PBR 은 이 API 응답에 없고 분석에서도 사용하지 않으므로 추출하지 않는다.
    EPS/BPS/매출액증가율 등 그 외 필드도 분석 미사용이라 무시.

    Args:
        ticker : 6자리 종목코드.
        annual : True 면 연간(1), False 면 분기(0).

    Returns:
        columns = [ticker, date, debt_ratio, roe]
        ``date`` 는 호출 시점(today). 빈 결과 시 빈 DataFrame.
    """
    data = _request(
        "GET",
        _FINANCIAL_RATIO_PATH,
        tr_id=_FINANCIAL_RATIO_TR,
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "fid_input_iscd": ticker,
            "fid_div_cls_code": "1" if annual else "0",
        },
    )

    output: list[dict[str, Any]] = data.get("output", []) or []
    if not output:
        logger.warning("KIS 재무비율 빈 결과: {}", ticker)
        return pd.DataFrame()

    latest = output[0]
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "date": date.today(),
                "debt_ratio": _safe_float(latest.get("lblt_rate")),
                "roe": _safe_float(latest.get("roe_val")),
            }
        ]
    )
