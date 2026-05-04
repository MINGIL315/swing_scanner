"""종목 유니버스 관리 — KOSPI200(pykrx) + S&P500(Wikipedia).

주요 함수:
    update_kospi200     : KRX에서 KOSPI200 구성종목을 가져와 DB 갱신
    update_sp500        : Wikipedia에서 S&P500 구성종목을 가져와 DB 갱신
    get_active_tickers  : DB에서 활성 종목 티커 목록 반환
    get_ticker_info     : 단일 종목 정보 반환
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Literal

import pandas as pd
import requests
from loguru import logger
from sqlalchemy import select, update

from scanner.config import settings
from scanner.db.models import Universe
from scanner.db.session import get_session

Market = Literal["KR", "US", "ALL"]

# Wikipedia S&P500 목록 URL
_SP500_WIKI_URL = (
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
)

# pykrx는 선택적 임포트 (네트워크 없는 환경에서도 import 자체는 성공)
try:
    from pykrx import stock as krx_stock  # type: ignore[import]
    _PYKRX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYKRX_AVAILABLE = False
    logger.warning("pykrx 미설치 — 한국 종목 데이터 취득 불가")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _upsert_tickers(
    rows: list[dict],
    market: str,
    session_obj,
) -> int:
    """Universe 테이블에 종목 목록을 upsert 한다.

    새 종목은 INSERT, 기존 종목은 name/sector/market_cap/is_active 갱신.
    이번 호출에 없는 종목은 is_active=False 로 비활성화한다.

    Returns:
        upsert 된 행 수
    """
    incoming_tickers: set[str] = {r["ticker"] for r in rows}

    # 기존 활성 종목 비활성화 (이번 목록에 없는 것)
    stmt = (
        update(Universe)
        .where(Universe.market == market, Universe.is_active.is_(True))
        .where(Universe.ticker.notin_(incoming_tickers))
        .values(is_active=False, updated_at=datetime.utcnow())
    )
    session_obj.execute(stmt)

    # upsert
    existing: dict[str, Universe] = {
        row.ticker: row
        for row in session_obj.execute(
            select(Universe).where(Universe.market == market)
        ).scalars()
    }

    count = 0
    for row in rows:
        ticker = row["ticker"]
        if ticker in existing:
            obj = existing[ticker]
            obj.name = row["name"]
            obj.sector = row.get("sector")
            obj.market_cap = row.get("market_cap")
            obj.is_active = True
            obj.updated_at = datetime.utcnow()
        else:
            obj = Universe(
                ticker=ticker,
                market=market,
                name=row["name"],
                sector=row.get("sector"),
                market_cap=row.get("market_cap"),
                is_active=True,
                updated_at=datetime.utcnow(),
            )
            session_obj.add(obj)
        count += 1

    return count


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def update_kospi200() -> int:
    """KRX에서 KOSPI200 구성종목을 가져와 Universe 테이블을 갱신한다.

    Returns:
        갱신(upsert)된 종목 수
    """
    if not _PYKRX_AVAILABLE:
        raise RuntimeError("pykrx가 설치되지 않았습니다.")

    today = _today_str()
    logger.info("KOSPI200 구성종목 조회 시작 (기준일: {})", today)

    # pykrx: 날짜 기준 KOSPI200 종목 코드 목록
    # 오류 시 빈 DataFrame이 반환될 수 있으므로 타입을 먼저 확인한다.
    _raw = krx_stock.get_index_portfolio_deposit_file("1028", today)
    if isinstance(_raw, pd.DataFrame):
        tickers: list[str] = [] if _raw.empty else _raw.iloc[:, 0].astype(str).tolist()
    elif isinstance(_raw, list):
        tickers = _raw
    else:
        tickers = list(_raw) if _raw else []

    if not tickers:
        logger.warning("KOSPI200 종목 목록이 비어있습니다 (휴장일 가능성).")
        return 0

    rows: list[dict] = []
    for ticker in tickers:
        try:
            name = krx_stock.get_market_ticker_name(ticker)
            rows.append({"ticker": ticker, "name": name or ticker, "sector": None})
            time.sleep(0.05)  # KRX 부하 방지
        except Exception as exc:
            logger.warning("티커 {} 이름 조회 실패: {}", ticker, exc)
            rows.append({"ticker": ticker, "name": ticker, "sector": None})

    with get_session() as sess:
        count = _upsert_tickers(rows, "KR", sess)

    logger.info("KOSPI200 {} 종목 upsert 완료", count)
    return count


def update_sp500() -> int:
    """Wikipedia에서 S&P500 구성종목을 스크래핑해 Universe 테이블을 갱신한다.

    Returns:
        갱신(upsert)된 종목 수
    """
    logger.info("S&P500 구성종목 스크래핑 시작 ({})", _SP500_WIKI_URL)

    try:
        resp = requests.get(
            _SP500_WIKI_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SwingScanner/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        tables: list[pd.DataFrame] = pd.read_html(
            resp.text,
            attrs={"id": "constituents"},
        )
        df = tables[0]
    except Exception as exc:
        logger.error("S&P500 Wikipedia 스크래핑 실패: {}", exc)
        raise

    # 컬럼명 정규화 (Wikipedia 표 구조가 바뀔 수 있음)
    col_map = {
        c: c.strip().lower().replace(" ", "_") for c in df.columns
    }
    df = df.rename(columns=col_map)

    # 필수 컬럼 확인
    symbol_col = next(
        (c for c in df.columns if "symbol" in c or "ticker" in c), None
    )
    name_col = next(
        (c for c in df.columns if "security" in c or "name" in c or "company" in c),
        None,
    )
    sector_col = next(
        (c for c in df.columns if "gics_sector" in c or "sector" in c), None
    )

    if symbol_col is None or name_col is None:
        raise ValueError(
            f"Wikipedia 표 컬럼 파싱 실패. 컬럼 목록: {list(df.columns)}"
        )

    rows: list[dict] = []
    for _, r in df.iterrows():
        ticker = str(r[symbol_col]).strip().replace(".", "-")  # BRK.B → BRK-B
        name = str(r[name_col]).strip()
        sector = str(r[sector_col]).strip() if sector_col else None
        rows.append({"ticker": ticker, "name": name, "sector": sector})

    with get_session() as sess:
        count = _upsert_tickers(rows, "US", sess)

    logger.info("S&P500 {} 종목 upsert 완료", count)
    return count


def get_active_tickers(market: Market = "ALL") -> list[str]:
    """DB에서 활성 종목 티커 목록을 반환한다.

    Args:
        market: "KR", "US", "ALL" 중 하나.

    Returns:
        티커 문자열 리스트.
    """
    with get_session() as sess:
        stmt = select(Universe.ticker).where(Universe.is_active.is_(True))
        if market != "ALL":
            stmt = stmt.where(Universe.market == market)
        rows = sess.execute(stmt).scalars().all()
    return list(rows)


def get_ticker_info(ticker: str) -> Universe | None:
    """단일 종목의 Universe 정보를 반환한다.

    Args:
        ticker: 종목 코드.

    Returns:
        Universe 인스턴스 또는 None (없으면).
    """
    with get_session() as sess:
        obj = sess.execute(
            select(Universe).where(Universe.ticker == ticker)
        ).scalar_one_or_none()
    return obj
