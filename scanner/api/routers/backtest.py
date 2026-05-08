"""POST /api/backtest/run 라우터."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["backtest"])

_VALID_PATTERNS = {"double_bottom", "golden_cross", "box_breakout", "pullback"}


class BacktestRequest(BaseModel):
    pattern_name: str = Field(..., description="패턴 이름")
    period_days: int = Field(default=90, ge=30, le=730, description="백테스트 기간 (일)")
    hold_days: int = Field(default=10, ge=1, le=60, description="최대 보유 일수")
    min_score: float = Field(default=70.0, ge=0, le=100, description="최소 신뢰도 점수")


@router.post("/backtest/run")
def run_backtest(req: BacktestRequest = Body(...)) -> dict[str, Any]:
    """패턴 백테스트를 실행하고 요약 통계를 반환한다."""
    if req.pattern_name not in _VALID_PATTERNS:
        raise HTTPException(
            status_code=422,
            detail=f"알 수 없는 패턴: {req.pattern_name}",
        )

    from scanner.kr.backtest.engine import run_backtest as _run

    result = _run(
        pattern_name=req.pattern_name,
        period_days=req.period_days,
        hold_days=req.hold_days,
        min_score=req.min_score,
    )
    return result
