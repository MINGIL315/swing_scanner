"""종목 유니버스 공용 DB 헬퍼.

KR/US 의 update_* 함수는 각 시장별 모듈에 있다:
    - scanner.data.kr.universe.update_kospi200
    - scanner.data.us.universe.update_sp500

주요 함수 (공용):
    get_active_tickers : DB에서 활성 종목 티커 목록 반환
    get_ticker_info    : 단일 종목 정보 반환
    _upsert_tickers    : KR/US update_* 가 공유하는 upsert 헬퍼
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update

from scanner.db.models import Universe
from scanner.db.session import get_session

Market = Literal["KR", "US", "ALL"]


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
