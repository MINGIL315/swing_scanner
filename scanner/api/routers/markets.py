"""GET /api/markets/summary, /api/markets/search 라우터."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from scanner.db.session import get_session

router = APIRouter(tags=["markets"])


@router.get("/markets/search")
def search_universe(
    q: str = Query(..., min_length=1, max_length=50, description="ticker 또는 한글명 부분 매치"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """활성 Universe 에서 ticker 또는 name 부분 매치로 검색한다."""
    from sqlalchemy import or_, select

    from scanner.db.models import Universe

    pattern = f"%{q}%"
    with get_session() as session:
        rows = session.execute(
            select(Universe.ticker, Universe.name, Universe.market, Universe.market_cap)
            .where(Universe.is_active.is_(True))
            .where(or_(
                Universe.ticker.ilike(pattern),
                Universe.name.ilike(pattern),
            ))
            .order_by(Universe.market_cap.desc().nulls_last())
            .limit(limit)
        ).all()

    return [
        {"ticker": r.ticker, "name": r.name, "market": r.market, "market_cap": r.market_cap}
        for r in rows
    ]


@router.get("/markets/summary")
def markets_summary(
    scan_date: date = Query(default=None, description="조회 날짜 (기본: 오늘)"),
) -> dict[str, Any]:
    """일일 시장 요약을 반환한다."""
    from sqlalchemy import func, select

    from scanner.db.models import ScanResult, Universe

    if scan_date is None:
        scan_date = date.today()

    with get_session() as session:
        all_rows = list(
            session.execute(
                select(ScanResult).where(ScanResult.scan_date == scan_date)
            ).scalars().all()
        )

        kr_tickers = set(
            session.execute(
                select(Universe.ticker).where(Universe.market == "KR")
            ).scalars().all()
        )
        us_tickers = set(
            session.execute(
                select(Universe.ticker).where(Universe.market == "US")
            ).scalars().all()
        )

        total_active = session.execute(
            select(func.count()).select_from(Universe).where(Universe.is_active.is_(True))
        ).scalar_one()

    kr_rows = [r for r in all_rows if r.ticker in kr_tickers]
    us_rows = [r for r in all_rows if r.ticker in us_tickers]

    _PATTERN_LABELS = {
        "double_bottom": "쌍바닥",
        "golden_cross":  "골든크로스",
        "box_breakout":  "박스 돌파",
        "pullback":      "눌림목",
    }

    pattern_dist: dict[str, int] = {}
    for r in all_rows:
        pattern_dist[r.pattern_name] = pattern_dist.get(r.pattern_name, 0) + 1

    return {
        "scan_date":        scan_date.isoformat(),
        "total_active":     total_active,
        "total_signals":    len(all_rows),
        "passed_filters":   sum(1 for r in all_rows if r.passed_filters),
        "kr": {
            "signals": len(kr_rows),
            "avg_score": (
                round(sum(r.confidence_score for r in kr_rows) / len(kr_rows), 1)
                if kr_rows else 0.0
            ),
        },
        "us": {
            "signals": len(us_rows),
            "avg_score": (
                round(sum(r.confidence_score for r in us_rows) / len(us_rows), 1)
                if us_rows else 0.0
            ),
        },
        "pattern_distribution": {
            k: {"count": pattern_dist.get(k, 0), "label": _PATTERN_LABELS.get(k, k)}
            for k in _PATTERN_LABELS
        },
        "top5": [
            {
                "ticker":           r.ticker,
                "pattern_name":     r.pattern_name,
                "confidence_score": round(r.confidence_score, 2),
            }
            for r in sorted(all_rows, key=lambda x: x.confidence_score, reverse=True)[:5]
        ],
    }
