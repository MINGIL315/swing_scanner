"""일일 스캔 파이프라인 오케스트레이터.

scan 명령어의 백엔드: 유니버스 갱신 → 데이터 fetch → 스캔 → DB 저장 → 요약 반환.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import and_, func, select

from scanner.config import (
    CONFIDENCE_THRESHOLD,
    FETCH_MAX_WORKERS,
    OHLCV_LOOKBACK_DAYS,
    settings,
)
from scanner.db.universe_db import get_active_tickers
from scanner.db.models import (
    Fundamental,
    OHLCVDaily,
    OHLCVIntraday,
    ScanResult,
    Universe,
)
from scanner.db.repository import get_scan_results, save_scan_results
from scanner.db.session import get_session
from scanner.kr.intraday import resample_to_4h
from scanner.kr.scanner import scan_universe


# ---------------------------------------------------------------------------
# 퍼블릭 API
# ---------------------------------------------------------------------------


def run_daily_pipeline(
    market: str = "ALL",
    skip_fetch: bool = False,
    min_confidence: float = CONFIDENCE_THRESHOLD,
    volume_filter: bool = True,
    fundamental_filter: bool = False,
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """일일 스캔 파이프라인을 실행하고 요약 통계를 반환한다.

    Args:
        market            : 스캔 대상 시장 ("KR", "US", "ALL").
        skip_fetch        : True이면 데이터 fetch를 생략하고 DB 기존 데이터로 스캔.
        min_confidence    : top_results 필터링 최소 신뢰도 점수.
        volume_filter     : False이면 거래량 필터 결과를 통과로 강제.
        fundamental_filter: True이면 재무 데이터를 로드해 필터 적용.
        patterns          : 저장·집계 대상 패턴 목록. None이면 전체.

    Returns:
        요약 통계 딕셔너리:
            scan_date         스캔 기준일
            market            스캔 시장
            total_tickers     스캔 종목 수
            total_patterns    탐지된 패턴 수
            saved_count       DB에 저장된 행 수
            duration_seconds  소요 시간 (초)
            top_results       상위 ScanResult 목록 (≤10개)
            pattern_dist      패턴별 탐지 건수 dict
    """
    t_start = time.monotonic()
    scan_date = date.today()

    logger.info("파이프라인 시작 | market={} skip_fetch={}", market, skip_fetch)

    # ── 1. 유니버스 갱신 (7일 이상 미갱신 시 자동 실행) ──────────
    _maybe_update_universe(market)

    # ── 2. 데이터 fetch ───────────────────────────────────────────
    if not skip_fetch:
        from scanner.data_pipeline import run_data_pipeline

        logger.info("OHLCV + 재무 fetch 시작")
        end_date = date.today()
        start_date = end_date - timedelta(days=OHLCV_LOOKBACK_DAYS)
        run_data_pipeline(market=market, start=start_date, end=end_date)
        logger.info("데이터 fetch 완료")

    # ── 3. 일봉 데이터 로드 ──────────────────────────────────────
    tickers = get_active_tickers(market if market != "ALL" else "ALL")
    if not tickers:
        logger.warning("활성 종목이 없습니다. 유니버스 갱신 필요.")
        return _empty_summary(scan_date, market, time.monotonic() - t_start)

    logger.info("일봉 데이터 로드 중 ({}개 종목)", len(tickers))
    daily_dfs = _load_daily_dfs(tickers)
    market_map = _load_market_map(tickers)

    # ── 4. 재무 데이터 로드 ──────────────────────────────────────
    fundamentals_map: dict[str, dict[str, float | None]] | None = None
    if fundamental_filter:
        logger.info("재무 데이터 로드 중")
        fundamentals_map = _load_fundamentals(tickers)

    # ── 4-2. 분봉 데이터 로드 (KR 만, 있으면 사용) ───────────────
    intraday_dfs = _load_intraday_dfs(tickers, market_map)
    if intraday_dfs:
        logger.info("4시간봉 로드 완료 ({}개 종목)", len(intraday_dfs))

    # ── 5. 스캔 실행 ─────────────────────────────────────────────
    logger.info("scan_universe 시작 ({}개 종목)", len(daily_dfs))
    results = scan_universe(
        daily_dfs=daily_dfs,
        market_map=market_map,
        fundamentals_map=fundamentals_map,
        intraday_dfs=intraday_dfs or None,
        max_workers=FETCH_MAX_WORKERS,
    )

    # ── 6. 옵션 적용 ─────────────────────────────────────────────
    if not volume_filter:
        for r in results:
            r.passed_volume = True

    if patterns:
        for r in results:
            pairs = [
                (pr, sc)
                for pr, sc in zip(r.pattern_results, r.confidence_scores)
                if pr.pattern_name in patterns
            ]
            if pairs:
                r.pattern_results, r.confidence_scores = map(list, zip(*pairs))
            else:
                r.pattern_results = []
                r.confidence_scores = []

    total_patterns = sum(len(r.pattern_results) for r in results)
    logger.info("scan_universe 완료 | 패턴 탐지 {}건", total_patterns)

    # ── 7. DB 저장 ───────────────────────────────────────────────
    with get_session() as session:
        saved_count = save_scan_results(results, session)
    logger.info("DB 저장 완료 | {}행", saved_count)

    # ── 8. 상위 결과 조회 ────────────────────────────────────────
    min_score_arg = min_confidence if min_confidence > 0 else None
    with get_session() as session:
        top_results = get_scan_results(
            scan_date=scan_date,
            session=session,
            min_score=min_score_arg,
        )

    # ── 9. 패턴 분포 집계 ────────────────────────────────────────
    pattern_dist: dict[str, int] = {}
    for r in results:
        for pr in r.pattern_results:
            pattern_dist[pr.pattern_name] = pattern_dist.get(pr.pattern_name, 0) + 1

    duration = time.monotonic() - t_start
    logger.info("파이프라인 완료 | 소요: {:.1f}초", duration)

    return {
        "scan_date": scan_date,
        "market": market,
        "total_tickers": len(tickers),
        "total_patterns": total_patterns,
        "saved_count": saved_count,
        "duration_seconds": duration,
        "top_results": top_results[:10],
        "pattern_dist": pattern_dist,
    }


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _maybe_update_universe(market: str) -> None:
    """유니버스가 7일 이상 미갱신인 경우 자동 갱신한다."""
    with get_session() as session:
        latest: datetime | None = session.execute(
            select(func.max(Universe.updated_at)).where(Universe.is_active.is_(True))
        ).scalar_one_or_none()

    if latest is None or (datetime.now() - latest).days >= 7:
        logger.info("유니버스 자동 갱신 시작")
        from scanner.kr.universe import update_kospi200
        from scanner.us.universe import update_sp500

        m = market.upper()
        if m in ("KR", "ALL"):
            count = update_kospi200()
            logger.info("KOSPI200 {}종목 갱신", count)
        if m in ("US", "ALL"):
            count = update_sp500()
            logger.info("S&P500 {}종목 갱신", count)
    else:
        logger.debug("유니버스 갱신 불필요 (최근 갱신: {})", latest.date())


def _load_daily_dfs(tickers: list[str], lookback_days: int = 500) -> dict[str, pd.DataFrame]:
    """DB에서 일봉 DataFrame을 티커별로 일괄 로드한다.

    Args:
        tickers      : 로드할 티커 목록.
        lookback_days: 오늘 기준 최대 소급 일수.

    Returns:
        ticker → DataFrame 매핑 (빈 데이터 종목은 제외).
    """
    start_date = date.today() - timedelta(days=lookback_days)

    with get_session() as session:
        rows = session.execute(
            select(OHLCVDaily)
            .where(OHLCVDaily.ticker.in_(tickers))
            .where(OHLCVDaily.date >= start_date)
            .order_by(OHLCVDaily.ticker, OHLCVDaily.date)
        ).scalars().all()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.ticker, []).append({
            "date": row.date,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "value": row.value,
        })

    return {
        ticker: pd.DataFrame(data)
        for ticker, data in grouped.items()
        if data
    }


def _load_intraday_dfs(
    tickers: list[str],
    market_map: dict[str, str],
    lookback_days: int = 30,
) -> dict[str, pd.DataFrame]:
    """KR 종목의 1분봉을 DB 에서 로드 → 4시간봉으로 합성하여 매핑 반환.

    CLAUDE.md §1 — 4시간봉 = 진입 타이밍 (거래량·캔들·RSI 다이버전스).
    분봉 데이터가 적재되지 않은 종목/시장은 매핑에 포함되지 않는다.
    1분봉 → 4시간봉 (drop_partial=True) 변환 후 ticker 별 dict 반환.

    drop_partial=True 인 이유: 13:00~15:30 부분봉(150분)은 거래량 비교 시
    완전봉(240분) 평균보다 항상 작아 ``last_vol > avg_vol`` 가 거짓이 됨.
    완전봉만 사용 → 일별 09:00 봉 1개, 22 영업일 ≈ 22 4h봉.

    Args:
        tickers      : 로드 대상 ticker 목록.
        market_map   : ticker → market. KR 만 처리, US 는 스킵.
        lookback_days: 오늘 기준 최대 소급 캘린더 일수 (영업일 ~22일).

    Returns:
        ticker → 4시간봉 DataFrame. 분봉 미적재 종목은 키 없음.
    """
    from datetime import datetime, time as time_t
    kr_tickers = [t for t in tickers if market_map.get(t) == "KR"]
    if not kr_tickers:
        return {}

    cutoff = datetime.combine(date.today() - timedelta(days=lookback_days), time_t.min)
    with get_session() as session:
        rows = session.execute(
            select(OHLCVIntraday)
            .where(OHLCVIntraday.ticker.in_(kr_tickers))
            .where(OHLCVIntraday.datetime >= cutoff)
            .order_by(OHLCVIntraday.ticker, OHLCVIntraday.datetime)
        ).scalars().all()

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.ticker, []).append({
            "ticker": r.ticker,
            "datetime": r.datetime,
            "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume,
        })

    result: dict[str, pd.DataFrame] = {}
    for ticker, data in grouped.items():
        if not data:
            continue
        df_1min = pd.DataFrame(data)
        df_4h = resample_to_4h(df_1min, drop_partial=True)
        if not df_4h.empty:
            result[ticker] = df_4h
    return result


def _load_market_map(tickers: list[str]) -> dict[str, str]:
    """티커 목록에 대한 시장 코드 매핑을 반환한다.

    Args:
        tickers: 조회할 티커 목록.

    Returns:
        ticker → "KR" | "US" 딕셔너리.
    """
    with get_session() as session:
        rows = session.execute(
            select(Universe.ticker, Universe.market)
            .where(Universe.ticker.in_(tickers))
        ).all()
    return {row.ticker: row.market for row in rows}


def _load_fundamentals(
    tickers: list[str],
) -> dict[str, dict[str, float | None]]:
    """최신 재무 지표와 시가총액을 티커별로 로드한다.

    Args:
        tickers: 조회할 티커 목록.

    Returns:
        ticker → {"market_cap"} 딕셔너리.
    """
    with get_session() as session:
        # 시가총액 (Universe 테이블)
        universe_rows = session.execute(
            select(Universe.ticker, Universe.market_cap)
            .where(Universe.ticker.in_(tickers))
        ).all()
        market_caps: dict[str, float | None] = {
            row.ticker: row.market_cap for row in universe_rows
        }

        # 최신 재무 지표 (Fundamental 테이블 — 티커별 최신 1행)
        max_date_subq = (
            select(
                Fundamental.ticker,
                func.max(Fundamental.date).label("max_date"),
            )
            .where(Fundamental.ticker.in_(tickers))
            .group_by(Fundamental.ticker)
            .subquery()
        )
        fund_rows = session.execute(
            select(Fundamental).join(
                max_date_subq,
                and_(
                    Fundamental.ticker == max_date_subq.c.ticker,
                    Fundamental.date == max_date_subq.c.max_date,
                ),
            )
        ).scalars().all()
        fund_map: dict[str, Fundamental] = {row.ticker: row for row in fund_rows}

    return {
        ticker: {"market_cap": market_caps.get(ticker)}
        for ticker in tickers
    }


def _empty_summary(scan_date: date, market: str, duration: float) -> dict[str, Any]:
    """빈 요약 통계를 반환한다."""
    return {
        "scan_date": scan_date,
        "market": market,
        "total_tickers": 0,
        "total_patterns": 0,
        "saved_count": 0,
        "duration_seconds": duration,
        "top_results": [],
        "pattern_dist": {},
    }
