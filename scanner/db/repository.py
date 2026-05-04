"""스캔 결과 저장/조회 레포지토리."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from scanner.db.models import ScanResult as ScanResultORM
from scanner.scanner import TickerScanResult


def save_scan_results(
    results: list[TickerScanResult],
    session: Session,
) -> int:
    """TickerScanResult 목록을 scan_results 테이블에 저장한다.

    같은 (scan_date, ticker, pattern_name) 조합이 이미 있으면
    confidence_score 등 수치 컬럼을 업데이트한다 (upsert).

    Args:
        results: scan_universe() 또는 analyze_ticker()의 반환값 목록.
        session: SQLAlchemy 세션.

    Returns:
        저장(upsert)된 행 수.
    """
    rows: list[dict[str, Any]] = []

    for res in results:
        passed_both = res.passed_volume and res.passed_fundamental
        for pattern_result, score in zip(res.pattern_results, res.confidence_scores):
            rows.append({
                "scan_date": res.scan_date,
                "ticker": res.ticker,
                "pattern_name": pattern_result.pattern_name,
                "confidence_score": score,
                "entry_price": pattern_result.entry_price,
                "stop_loss": pattern_result.stop_loss,
                "target_price": pattern_result.target_price,
                "risk_reward_ratio": pattern_result.risk_reward_ratio,
                "entry_signal_strength": None,
                "entry_signals": None,
                "pattern_details": pattern_result.details,
                "trend_weekly": pattern_result.details.get("weekly_trend"),
                "passed_filters": passed_both,
            })

    if not rows:
        return 0

    stmt = sqlite_insert(ScanResultORM).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=None,
        index_where=None,
        set_={
            "confidence_score": stmt.excluded.confidence_score,
            "entry_price": stmt.excluded.entry_price,
            "stop_loss": stmt.excluded.stop_loss,
            "target_price": stmt.excluded.target_price,
            "risk_reward_ratio": stmt.excluded.risk_reward_ratio,
            "pattern_details": stmt.excluded.pattern_details,
            "trend_weekly": stmt.excluded.trend_weekly,
            "passed_filters": stmt.excluded.passed_filters,
        },
    )
    session.execute(stmt)
    return len(rows)


def get_scan_results(
    scan_date: date,
    session: Session,
    market_tickers: list[str] | None = None,
    min_score: float | None = None,
    passed_filters_only: bool = False,
) -> list[ScanResultORM]:
    """조건에 맞는 스캔 결과를 반환한다.

    Args:
        scan_date          : 조회할 스캔 날짜.
        session            : SQLAlchemy 세션.
        market_tickers     : 조회할 티커 목록 (None이면 전체).
        min_score          : 최소 신뢰도 점수 (None이면 제한 없음).
        passed_filters_only: True이면 passed_filters=True인 결과만.

    Returns:
        ScanResultORM 인스턴스 목록 (confidence_score 내림차순).
    """
    stmt = (
        select(ScanResultORM)
        .where(ScanResultORM.scan_date == scan_date)
    )
    if market_tickers is not None:
        stmt = stmt.where(ScanResultORM.ticker.in_(market_tickers))
    if min_score is not None:
        stmt = stmt.where(ScanResultORM.confidence_score >= min_score)
    if passed_filters_only:
        stmt = stmt.where(ScanResultORM.passed_filters.is_(True))

    stmt = stmt.order_by(ScanResultORM.confidence_score.desc())
    return list(session.execute(stmt).scalars().all())
