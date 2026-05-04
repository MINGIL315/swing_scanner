"""스캔 결과 저장/조회 레포지토리."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from scanner.db.models import ScanResult as ScanResultORM
from scanner.scanner import TickerScanResult


def save_scan_results(
    results: list[TickerScanResult],
    session: Session,
) -> int:
    """TickerScanResult 목록을 scan_results 테이블에 저장한다.

    같은 (scan_date, ticker) 의 기존 행을 삭제한 뒤 새 행을 삽입한다.
    (하루에 한 번 전체 재스캔을 가정하므로 delete-then-insert 가 적합하다.)

    Args:
        results: scan_universe() 또는 analyze_ticker()의 반환값 목록.
        session: SQLAlchemy 세션.

    Returns:
        삽입된 행 수.
    """
    if not results:
        return 0

    # 이미 존재하는 같은 날짜/종목 행 삭제
    tickers = list({r.ticker for r in results})
    scan_dates = list({r.scan_date for r in results})
    for scan_date in scan_dates:
        session.execute(
            delete(ScanResultORM)
            .where(ScanResultORM.scan_date == scan_date)
            .where(ScanResultORM.ticker.in_(tickers))
        )

    orm_rows: list[ScanResultORM] = []
    for res in results:
        passed_both = res.passed_volume and res.passed_fundamental
        for pattern_result, score in zip(res.pattern_results, res.confidence_scores):
            orm_rows.append(ScanResultORM(
                scan_date=res.scan_date,
                ticker=res.ticker,
                pattern_name=pattern_result.pattern_name,
                confidence_score=score,
                entry_price=pattern_result.entry_price,
                stop_loss=pattern_result.stop_loss,
                target_price=pattern_result.target_price,
                risk_reward_ratio=pattern_result.risk_reward_ratio,
                entry_signal_strength=None,
                entry_signals=None,
                pattern_details=pattern_result.details,
                trend_weekly=res.weekly_direction,
                passed_filters=passed_both,
            ))

    session.add_all(orm_rows)
    return len(orm_rows)


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
