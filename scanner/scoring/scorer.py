"""신뢰도 점수 계산 (CLAUDE.md §6)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from scanner.config import CONFIDENCE_WEIGHTS, MA_MEDIUM
from scanner.indicators.moving_average import sma
from scanner.indicators.rsi import rsi
from scanner.patterns.base import PatternResult


@dataclass
class ScoringInput:
    """신뢰도 점수 계산에 필요한 입력 데이터.

    Args:
        pattern_result       : 패턴 탐지기가 반환한 결과.
        weekly_trend_direction: 주봉 추세 방향 ("uptrend" | "sideways" | "downtrend").
        weekly_trend_strength : 주봉 추세 강도 (MA20 대비 이격률, 0 이상).
        daily_df             : 일봉 OHLCV DataFrame.
    """

    pattern_result: PatternResult
    weekly_trend_direction: str
    weekly_trend_strength: float
    daily_df: pd.DataFrame


def calculate_confidence_score(inp: ScoringInput) -> float:
    """CLAUDE.md §6 기준 신뢰도 점수를 계산한다 (0~100).

    5개 컴포넌트 가중 합산:
    - weekly_trend  30%: 주봉 추세 방향
    - pattern_clarity 25%: 패턴 raw_score
    - volume        20%: 거래량 비율
    - ma_alignment  15%: MA 정배열
    - rsi           10%: RSI 정상 범위

    Args:
        inp: ScoringInput 인스턴스.

    Returns:
        0.0 ~ 100.0 범위의 신뢰도 점수.
    """
    w = CONFIDENCE_WEIGHTS

    # 1. 주봉 추세 (30%)
    weekly_score = _weekly_trend_score(inp.weekly_trend_direction)

    # 2. 패턴 명확도 (25%) — raw_score 는 이미 0~100
    pattern_score = float(inp.pattern_result.raw_score)

    # 3. 거래량 (20%) — details['vol_ratio'] 재사용
    vol_score = _volume_score(inp.pattern_result.details.get("vol_ratio", 0.0))

    # 4. MA 정배열 (15%)
    ma_score = _ma_alignment_score(inp.pattern_result.details)

    # 5. RSI (10%)
    rsi_score = _rsi_score(inp.daily_df)

    total = (
        weekly_score * w["weekly_trend"]
        + pattern_score * w["pattern_clarity"]
        + vol_score * w["volume"]
        + ma_score * w["ma_alignment"]
        + rsi_score * w["rsi"]
    )
    return round(min(100.0, max(0.0, total)), 2)


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _weekly_trend_score(direction: str) -> float:
    """주봉 추세 방향을 0~100 점수로 변환한다."""
    return {"uptrend": 100.0, "sideways": 40.0, "downtrend": 0.0}.get(direction, 0.0)


def _volume_score(vol_ratio: float) -> float:
    """거래량 비율(평균 대비)을 0~100 점수로 변환한다.

    1.0 → 0점, 1.5 이상 → 100점 (선형 보간).
    """
    return float(min(100.0, max(0.0, (vol_ratio - 1.0) / 0.5 * 100.0)))


def _ma_alignment_score(details: dict) -> float:
    """MA 정배열 여부를 0 또는 100으로 반환한다.

    details 에 ma5/ma20/ma60 이 있으면 직접 비교,
    없으면 100 (패턴 자체가 정배열을 요구하므로 탐지 성공 = 정배열).
    """
    ma5 = details.get("ma5")
    ma20 = details.get("ma20")
    ma60 = details.get("ma60")
    if ma5 is None or ma20 is None or ma60 is None:
        return 100.0
    return 100.0 if float(ma5) > float(ma20) > float(ma60) else 0.0


def _rsi_score(daily_df: pd.DataFrame) -> float:
    """최근 RSI가 40~70 범위 내이면 100, 범위 밖이면 거리 비례 감점한다.

    계산에 필요한 데이터가 부족하면 중립 50점을 반환한다.
    """
    if "close" not in daily_df.columns or len(daily_df) < 15:
        return 50.0

    rsi_series = rsi(daily_df["close"], 14).dropna()
    if len(rsi_series) == 0:
        return 50.0

    val = float(rsi_series.iloc[-1])

    if 40.0 <= val <= 70.0:
        return 100.0

    # 범위 밖: 가장 가까운 경계까지의 거리를 기준으로 감점
    # 경계에서 0점이 되는 기준: 하단 40→0 = 40포인트, 상단 70→100 = 30포인트
    if val < 40.0:
        return float(max(0.0, (val - 0.0) / 40.0 * 100.0))
    else:  # val > 70.0
        return float(max(0.0, (100.0 - val) / 30.0 * 100.0))
