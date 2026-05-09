"""GET /api/stocks/{ticker}/ohlcv, /api/stocks/{ticker}/analysis 라우터."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from scanner.db.models import Universe
from scanner.db.session import get_session

router = APIRouter(tags=["stocks"])


def _resolve_market(ticker: str, session: Session) -> str:
    """Universe 테이블에서 ticker 의 market 을 반환한다.

    ticker.isdigit() 같은 패턴 추측 대신 DB 를 진실의 원천으로 사용 — KOSPI200
    의 영숫자 6자리 ticker (예: '0126Z0' 삼성에피스홀딩스) 도 정확히 KR 로 분기.

    Args:
        ticker : 대문자 정규화된 종목 코드.
        session: 활성 SQLAlchemy 세션.

    Returns:
        ``"KR"`` / ``"US"`` / 미등록 종목은 ``"US"`` fallback.
    """
    market = session.execute(
        select(Universe.market).where(Universe.ticker == ticker)
    ).scalar_one_or_none()
    return market or "US"


@router.get("/stocks/{ticker}/ohlcv")
def stock_ohlcv(
    ticker: str,
    days: int = Query(default=1000, ge=10, le=2000, description="최근 N영업일치 (default=1000 ≈ 약 4년)"),
) -> dict[str, Any]:
    """일봉 OHLCV + 이동평균 + RSI 를 반환한다."""
    from scanner.db.models import OHLCVDaily
    import json
    import pandas as pd

    ticker = ticker.upper()

    with get_session() as session:
        market = _resolve_market(ticker, session)
        rows = list(
            session.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.ticker == ticker)
                .order_by(OHLCVDaily.date.desc())
                .limit(days)
            ).scalars().all()
        )

    if market == "KR":
        from scanner.kr.reports.html_report import _build_ohlcv_json
    else:
        from scanner.us.reports.html_report import _build_ohlcv_json

    if not rows:
        raise HTTPException(status_code=404, detail=f"{ticker} OHLCV 데이터 없음")

    rows.sort(key=lambda r: r.date)
    df = pd.DataFrame([
        {
            "date":   r.date.isoformat(),
            "open":   r.open,
            "high":   r.high,
            "low":    r.low,
            "close":  r.close,
            "volume": r.volume,
        }
        for r in rows
    ])

    # {"daily": {candles, ma5, ma20, ma60, volume, rsi}, "weekly": {...}} 형태.
    # web/stock.html 의 일/주봉 토글이 daily/weekly 둘 다 사용.
    return json.loads(_build_ohlcv_json(df))


@router.get("/stocks/{ticker}/analysis")
def stock_analysis(
    ticker: str,
    scan_date: date = Query(default=None, description="조회 날짜 (기본: 오늘)"),
) -> list[dict[str, Any]]:
    """특정 종목의 스캔 결과 + AI 코멘트를 반환한다."""
    from scanner.db.models import ScanResult

    if scan_date is None:
        scan_date = date.today()

    ticker = ticker.upper()

    with get_session() as session:
        market = _resolve_market(ticker, session)
        rows = list(
            session.execute(
                select(ScanResult)
                .where(ScanResult.scan_date == scan_date)
                .where(ScanResult.ticker == ticker)
                .order_by(ScanResult.confidence_score.desc())
            ).scalars().all()
        )

        # 종목 이름
        name_row = session.execute(
            select(Universe.name).where(Universe.ticker == ticker)
        ).scalar_one_or_none()
        name = name_row or ""

    if market == "KR":
        from scanner.kr.reports.comment_generator import generate_comment
    else:
        from scanner.us.reports.comment_generator import generate_comment

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} — {scan_date} 스캔 결과 없음",
        )

    results = []
    for r in rows:
        row_dict = {
            "pattern_name":      r.pattern_name,
            "trend_weekly":      r.trend_weekly,
            "entry_price":       r.entry_price,
            "stop_loss":         r.stop_loss,
            "target_price":      r.target_price,
            "risk_reward_ratio": r.risk_reward_ratio,
        }
        results.append({
            "ticker":            ticker,
            "name":              name,
            "scan_date":         scan_date.isoformat(),
            "pattern_name":      r.pattern_name,
            "confidence_score":  round(r.confidence_score, 2),
            "entry_price":       r.entry_price,
            "stop_loss":         r.stop_loss,
            "target_price":      r.target_price,
            "risk_reward_ratio": r.risk_reward_ratio,
            "trend_weekly":      r.trend_weekly,
            "passed_filters":    r.passed_filters,
            "ai_comment":        generate_comment(row_dict),
        })

    return results
