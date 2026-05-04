"""스윙 스캐너 핵심 로직.

analyze_ticker() : 단일 종목에 대해 패턴 탐지 → 점수 → 필터를 일괄 수행한다.
scan_universe()  : 활성 종목 전체를 ThreadPoolExecutor로 병렬 스캔한다.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
from loguru import logger

from scanner.config import FETCH_MAX_WORKERS
from scanner.filtering.fundamental_filter import passes_fundamental_filter
from scanner.filtering.volume_filter import passes_volume_filter
from scanner.patterns import ALL_DETECTORS
from scanner.patterns.base import PatternResult
from scanner.patterns.trend import detect_weekly_trend
from scanner.scoring.scorer import ScoringInput, calculate_confidence_score


@dataclass
class TickerScanResult:
    """단일 종목 스캔 결과.

    Attributes:
        ticker              : 종목 코드.
        market              : "KR" 또는 "US".
        scan_date           : 스캔 기준일.
        pattern_results     : 탐지된 패턴 결과 목록.
        confidence_scores   : 각 패턴의 신뢰도 점수 (pattern_results와 동일 순서).
        passed_volume       : 유동성 필터 통과 여부.
        passed_fundamental  : 재무 필터 통과 여부.
        volume_details      : 유동성 필터 상세.
        fundamental_details : 재무 필터 상세.
    """

    ticker: str
    market: str
    scan_date: date
    pattern_results: list[PatternResult] = field(default_factory=list)
    confidence_scores: list[float] = field(default_factory=list)
    passed_volume: bool = False
    passed_fundamental: bool = False
    volume_details: dict[str, Any] = field(default_factory=dict)
    fundamental_details: dict[str, Any] = field(default_factory=dict)
    weekly_direction: str = "sideways"


def analyze_ticker(
    ticker: str,
    market: str,
    daily_df: pd.DataFrame,
    fundamentals: dict[str, float | None] | None = None,
) -> TickerScanResult:
    """단일 종목에 대해 패턴 탐지 → 점수 계산 → 필터 적용을 수행한다.

    Args:
        ticker      : 종목 코드.
        market      : "KR" 또는 "US".
        daily_df    : 일봉 OHLCV DataFrame (최신 행이 마지막).
        fundamentals: {'market_cap', 'per', 'debt_ratio'} 딕셔너리.
                      None 이면 재무 필터를 건너뛴다 (passed_fundamental=False).

    Returns:
        TickerScanResult 인스턴스.
    """
    scan_date = date.today()
    result = TickerScanResult(ticker=ticker, market=market, scan_date=scan_date)

    if daily_df.empty:
        logger.warning("{} daily_df가 비어 있어 스킵", ticker)
        return result

    # ── 주봉 추세 (점수 계산에 공유) ────────────────────────────
    weekly_direction, weekly_strength = _get_weekly_trend(daily_df)
    result.weekly_direction = weekly_direction

    # ── 패턴 탐지 + 점수 계산 ────────────────────────────────────
    for detector in ALL_DETECTORS:
        try:
            pattern_result = detector.detect(daily_df, ticker)
        except Exception as exc:
            logger.warning("{} {} 탐지 중 오류: {}", ticker, detector.name, exc)
            continue

        if pattern_result is None:
            continue

        inp = ScoringInput(
            pattern_result=pattern_result,
            weekly_trend_direction=weekly_direction,
            weekly_trend_strength=weekly_strength,
            daily_df=daily_df,
        )
        score = calculate_confidence_score(inp)
        result.pattern_results.append(pattern_result)
        result.confidence_scores.append(score)

    # ── 거래량 필터 ───────────────────────────────────────────────
    try:
        result.passed_volume, result.volume_details = passes_volume_filter(daily_df, market)
    except Exception as exc:
        logger.warning("{} 거래량 필터 오류: {}", ticker, exc)

    # ── 재무 필터 ─────────────────────────────────────────────────
    if fundamentals is not None:
        try:
            result.passed_fundamental, result.fundamental_details = passes_fundamental_filter(
                ticker, market, fundamentals
            )
        except Exception as exc:
            logger.warning("{} 재무 필터 오류: {}", ticker, exc)

    return result


def scan_universe(
    daily_dfs: dict[str, pd.DataFrame],
    market_map: dict[str, str],
    fundamentals_map: dict[str, dict[str, float | None]] | None = None,
    max_workers: int = FETCH_MAX_WORKERS,
) -> list[TickerScanResult]:
    """전체 종목을 병렬 스캔한다.

    Args:
        daily_dfs      : ticker → 일봉 DataFrame 매핑.
        market_map     : ticker → "KR" | "US" 매핑.
        fundamentals_map: ticker → fundamentals dict 매핑. None이면 재무 필터 생략.
        max_workers    : ThreadPoolExecutor 워커 수.

    Returns:
        탐지된 패턴이 1개 이상이거나 필터를 모두 통과한 종목의 결과 목록.
        (빈 결과도 포함 — 상위 레이어에서 필터링)
    """
    tickers = list(daily_dfs.keys())
    logger.info("scan_universe 시작: {}개 종목, workers={}", len(tickers), max_workers)

    results: list[TickerScanResult] = []

    def _run(ticker: str) -> TickerScanResult:
        return analyze_ticker(
            ticker=ticker,
            market=market_map.get(ticker, "US"),
            daily_df=daily_dfs[ticker],
            fundamentals=fundamentals_map.get(ticker) if fundamentals_map else None,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run, t): t for t in tickers}
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.error("{} scan_universe 처리 실패: {}", ticker, exc)

    logger.info(
        "scan_universe 완료: {}개 종목 처리, 패턴 탐지 {}건",
        len(results),
        sum(len(r.pattern_results) for r in results),
    )
    return results


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _get_weekly_trend(daily_df: pd.DataFrame) -> tuple[str, float]:
    """일봉 DataFrame에서 주봉 추세 방향과 강도를 반환한다.

    데이터 부족 또는 오류 시 ("sideways", 0.0) 를 반환한다.
    """
    try:
        from scanner.patterns.pullback import _resample_weekly  # 재사용
        weekly_df = _resample_weekly(daily_df)
        trend = detect_weekly_trend(weekly_df)
        return trend.direction, trend.strength
    except Exception:
        return "sideways", 0.0
