"""GET /api/patterns/{pattern_name}/stats 라우터."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from scanner.db.session import get_session

router = APIRouter(tags=["patterns"])

_VALID_PATTERNS = {"double_bottom", "golden_cross", "box_breakout", "pullback"}
_PATTERN_LABELS = {
    "double_bottom": "쌍바닥",
    "golden_cross":  "골든크로스",
    "box_breakout":  "박스 돌파",
    "pullback":      "눌림목",
}


@router.get("/patterns/{pattern_name}/stats")
def pattern_stats(
    pattern_name: str,
    period: int = Query(default=30, ge=1, le=365, description="최근 N일"),
) -> dict[str, Any]:
    """패턴별 탐지 통계를 반환한다."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from scanner.db.models import ScanResult

    if pattern_name not in _VALID_PATTERNS:
        raise HTTPException(
            status_code=404,
            detail=f"알 수 없는 패턴: {pattern_name}. 가능: {list(_VALID_PATTERNS)}",
        )

    since = date.today() - timedelta(days=period)

    with get_session() as session:
        rows = list(
            session.execute(
                select(ScanResult)
                .where(ScanResult.pattern_name == pattern_name)
                .where(ScanResult.scan_date >= since)
            ).scalars().all()
        )

    total = len(rows)
    avg_score = round(sum(r.confidence_score for r in rows) / total, 2) if total else 0.0
    passed = sum(1 for r in rows if r.passed_filters)

    daily: dict[str, int] = {}
    for r in rows:
        key = r.scan_date.isoformat()
        daily[key] = daily.get(key, 0) + 1

    return {
        "pattern_name":  pattern_name,
        "pattern_label": _PATTERN_LABELS[pattern_name],
        "period_days":   period,
        "total_signals": total,
        "passed_filters": passed,
        "avg_confidence": avg_score,
        "daily_counts":  daily,
    }


@router.get("/patterns")
def list_patterns() -> list[dict[str, Any]]:
    """지원하는 패턴 목록을 반환한다."""
    from datetime import date

    from sqlalchemy import func, select

    from scanner.db.models import ScanResult

    today = date.today()

    with get_session() as session:
        counts = {
            row[0]: row[1]
            for row in session.execute(
                select(ScanResult.pattern_name, func.count())
                .where(ScanResult.scan_date == today)
                .group_by(ScanResult.pattern_name)
            ).all()
        }

    return [
        {
            "pattern_name":  k,
            "pattern_label": v,
            "today_count":   counts.get(k, 0),
        }
        for k, v in _PATTERN_LABELS.items()
    ]
