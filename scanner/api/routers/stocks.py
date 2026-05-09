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
    """일봉 + 주봉 + (KR 만) 4시간봉 OHLCV 차트 데이터를 반환한다."""
    from datetime import datetime, time as time_t, timedelta

    from scanner.db.models import OHLCVDaily, OHLCVIntraday
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

        # KR 종목이면 OHLCVIntraday 1분봉도 로드 (최근 30일치)
        intraday_rows: list[OHLCVIntraday] = []
        if market == "KR":
            cutoff = datetime.combine(
                date.today() - timedelta(days=30), time_t.min
            )
            intraday_rows = list(
                session.execute(
                    select(OHLCVIntraday)
                    .where(OHLCVIntraday.ticker == ticker)
                    .where(OHLCVIntraday.datetime >= cutoff)
                    .order_by(OHLCVIntraday.datetime)
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

    # KR 분봉 → 4시간봉 합성 (적재된 분봉이 있을 때만)
    intraday_4h_df: pd.DataFrame | None = None
    if intraday_rows:
        from scanner.kr.intraday import resample_to_minutes

        df_1min = pd.DataFrame([
            {
                "ticker":   r.ticker,
                "datetime": r.datetime,
                "open":     r.open,
                "high":     r.high,
                "low":      r.low,
                "close":    r.close,
                "volume":   r.volume,
            }
            for r in intraday_rows
        ])
        intraday_4h_df = resample_to_minutes(df_1min, rule="4h", drop_partial=False)

    # {"daily": {...}, "weekly": {...}, "4h": {...}(KR+분봉적재시)} 형태
    return json.loads(_build_ohlcv_json(df, intraday_4h_df=intraday_4h_df))


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
            # Phase C-3b 진입 타이밍 신호 (4시간봉 = 60분봉 기반 평가)
            "entry_signal_strength": (
                round(r.entry_signal_strength, 1)
                if r.entry_signal_strength is not None else None
            ),
            "entry_signals":     r.entry_signals,  # dict[str, bool] 또는 None
            "ai_comment":        generate_comment(row_dict),
        })

    return results
