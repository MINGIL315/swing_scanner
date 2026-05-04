"""SQLAlchemy 2.0 모델 정의 (총 7개 테이블).

테이블:
    - universe         : 종목 마스터 (KR/US 통합)
    - ohlcv_daily      : 일봉 OHLCV
    - ohlcv_weekly     : 주봉 OHLCV (멀티 타임프레임 — 추세 판단용)
    - ohlcv_intraday   : 60분봉 (4시간봉 = 60분 4개 결합)
    - fundamentals     : 재무 지표 (PER/PBR/부채비율/ROE)
    - scan_results     : 스캐너 출력 (패턴 + 신뢰도 점수)
    - backtest_results : 백테스트 요약
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 모델의 공통 베이스."""


# ---------------------------------------------------------------------------
# 1. Universe — 종목 마스터
# ---------------------------------------------------------------------------


class Universe(Base):
    """스캔 대상 종목 마스터 테이블.

    KR(코스피200), US(S&P500) 약 700종목을 단일 테이블에 통합 저장한다.
    """

    __tablename__ = "universe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    market: Mapped[str] = mapped_column(String(2), nullable=False)  # "KR" | "US"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_universe_market_active", "market", "is_active"),
    )


# ---------------------------------------------------------------------------
# 2. OHLCVDaily — 일봉
# ---------------------------------------------------------------------------


class OHLCVDaily(Base):
    """일봉 OHLCV. 패턴 탐지의 메인 데이터."""

    __tablename__ = "ohlcv_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("universe.ticker"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # 거래대금

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ohlcv_daily_ticker_date"),
        Index("ix_ohlcv_daily_ticker_date", "ticker", "date"),
    )


# ---------------------------------------------------------------------------
# 3. OHLCVWeekly — 주봉
# ---------------------------------------------------------------------------


class OHLCVWeekly(Base):
    """주봉 OHLCV. 큰 추세 확인용."""

    __tablename__ = "ohlcv_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("universe.ticker"), nullable=False
    )
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ticker", "week_start_date", name="uq_ohlcv_weekly_ticker_week"
        ),
        Index("ix_ohlcv_weekly_ticker_week", "ticker", "week_start_date"),
    )


# ---------------------------------------------------------------------------
# 4. OHLCVIntraday — 60분봉
# ---------------------------------------------------------------------------


class OHLCVIntraday(Base):
    """60분봉 OHLCV. 4시간봉 = 60분 4개 결합으로 산출하여 진입 타이밍에 사용."""

    __tablename__ = "ohlcv_intraday"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("universe.ticker"), nullable=False
    )
    datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ticker", "datetime", name="uq_ohlcv_intraday_ticker_dt"
        ),
        Index("ix_ohlcv_intraday_ticker_dt", "ticker", "datetime"),
    )


# ---------------------------------------------------------------------------
# 5. Fundamental — 재무 지표
# ---------------------------------------------------------------------------


class Fundamental(Base):
    """재무 지표 (PER/PBR/부채비율/ROE). 일자별 스냅샷."""

    __tablename__ = "fundamentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("universe.ticker"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    per: Mapped[float | None] = mapped_column(Float, nullable=True)
    pbr: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # 부채비율 %
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_fundamentals_ticker_date"),
        Index("ix_fundamentals_ticker_date", "ticker", "date"),
    )


# ---------------------------------------------------------------------------
# 6. ScanResult — 스캐너 출력
# ---------------------------------------------------------------------------


class ScanResult(Base):
    """매일 스캐너 실행 결과. 종목별/패턴별 1행."""

    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_date: Mapped[date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("universe.ticker"), nullable=False
    )
    pattern_name: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0~100

    # 매매 시나리오
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 신호 강도 / 부가 정보
    entry_signal_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_signals: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pattern_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    trend_weekly: Mapped[str | None] = mapped_column(String(20), nullable=True)  # up/flat/down
    passed_filters: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_scan_results_date_pattern", "scan_date", "pattern_name"),
        Index("ix_scan_results_ticker", "ticker"),
    )


# ---------------------------------------------------------------------------
# 7. BacktestResult — 백테스트 요약
# ---------------------------------------------------------------------------


class BacktestResult(Base):
    """패턴별 백테스트 요약. 한 회 실행당 1행."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_name: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)        # 0~1
    avg_return: Mapped[float] = mapped_column(Float, nullable=False)      # 평균 수익률
    avg_loss: Mapped[float] = mapped_column(Float, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_backtest_pattern_period", "pattern_name", "period_start"),
    )


__all__ = [
    "Base",
    "Universe",
    "OHLCVDaily",
    "OHLCVWeekly",
    "OHLCVIntraday",
    "Fundamental",
    "ScanResult",
    "BacktestResult",
]
