"""GET /api/scan-results 라우터."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from scanner.db.repository import get_scan_results
from scanner.db.session import get_session

router = APIRouter(tags=["scan-results"])

_VALID_PATTERNS = {"double_bottom", "golden_cross", "box_breakout", "pullback"}


@router.get("/scan-results")
def list_scan_results(
    scan_date: date = Query(default=None, description="조회 날짜 (YYYY-MM-DD, 기본: 오늘)"),
    pattern: str | None = Query(default=None, description="패턴 필터"),
    market: str | None = Query(default=None, description="시장 필터 (KR | US)"),
    min_score: float = Query(default=0.0, ge=0, le=100, description="최소 신뢰도 점수"),
    top: int = Query(default=50, ge=1, le=500, description="최대 반환 건수"),
) -> list[dict[str, Any]]:
    """스캔 결과 목록을 반환한다."""
    if scan_date is None:
        scan_date = date.today()

    from sqlalchemy import select
    from scanner.db.models import Universe

    market_tickers: list[str] | None = None
    if market:
        with get_session() as session:
            market_tickers = list(
                session.execute(
                    select(Universe.ticker).where(
                        Universe.market == market.upper(),
                        Universe.is_active.is_(True),
                    )
                ).scalars().all()
            )

    with get_session() as session:
        rows = get_scan_results(
            scan_date=scan_date,
            session=session,
            market_tickers=market_tickers,
            min_score=min_score if min_score > 0 else None,
        )

    if pattern and pattern in _VALID_PATTERNS:
        rows = [r for r in rows if r.pattern_name == pattern]

    return [
        {
            "scan_date":         r.scan_date.isoformat(),
            "ticker":            r.ticker,
            "pattern_name":      r.pattern_name,
            "confidence_score":  round(r.confidence_score, 2),
            "entry_price":       r.entry_price,
            "stop_loss":         r.stop_loss,
            "target_price":      r.target_price,
            "risk_reward_ratio": r.risk_reward_ratio,
            "trend_weekly":      r.trend_weekly,
            "passed_filters":    r.passed_filters,
        }
        for r in rows[:top]
    ]
