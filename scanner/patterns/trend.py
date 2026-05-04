"""주봉 추세 판정 모듈."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from scanner.indicators.moving_average import sma

TrendDirection = Literal["uptrend", "downtrend", "sideways"]

# 추세 판정 임계값
_UPTREND_SLOPE_MIN: float = -0.005   # 60주선 4주 기울기 ≥ -0.5%
_DOWNTREND_SLOPE_MAX: float = -0.01  # 60주선 4주 기울기 ≤ -1.0%
_SLOPE_WINDOW: int = 4               # 기울기 산출 구간 (주)
_MA_FAST: int = 20                   # 추세 판정 단기 이동평균 (주봉)
_MA_SLOW: int = 60                   # 추세 판정 장기 이동평균 (주봉)
_MIN_ROWS: int = _MA_SLOW + _SLOPE_WINDOW  # 최소 필요 행 수


@dataclass
class WeeklyTrend:
    """주봉 추세 판정 결과.

    Attributes:
        direction       : 추세 방향 ('uptrend' | 'downtrend' | 'sideways').
        strength        : (종가 − MA20) / MA20 × 100 (%). 양수=MA 위, 음수=MA 아래.
        ma20_above_ma60 : MA20 > MA60 여부.
        price_above_ma20: 현재 종가 > MA20 여부.
        ma60_slope      : 최근 4주간 MA60의 선형 기울기 (가격 단위 기준 % 변화율).
        details         : 판정에 사용된 수치 원본 (디버깅용).
    """

    direction: TrendDirection
    strength: float
    ma20_above_ma60: bool
    price_above_ma20: bool
    ma60_slope: float
    details: dict[str, Any] = field(default_factory=dict)


def _calc_slope_pct(series: pd.Series, window: int) -> float:
    """시계열 마지막 window 개 값의 선형 기울기를 % 변화율로 반환한다.

    기울기 = linregress slope / 첫 값 (% 단위).
    데이터가 부족하거나 첫 값이 0이면 0.0 반환.
    """
    if len(series) < window:
        return 0.0
    tail = series.dropna().iloc[-window:]
    if len(tail) < 2:
        return 0.0
    x = np.arange(len(tail), dtype=float)
    y = tail.values.astype(float)
    # 간단한 최소제곱 기울기
    x_mean, y_mean = x.mean(), y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return 0.0
    slope = ((x - x_mean) * (y - y_mean)).sum() / denom
    base = y[0] if y[0] != 0 else 1.0
    return float(slope / base)


def detect_weekly_trend(weekly_df: pd.DataFrame) -> WeeklyTrend:
    """주봉 DataFrame에서 추세 방향과 강도를 판정한다.

    판정 우선 순위:
        1. uptrend  : MA20 > MA60  AND  종가 > MA20  AND  MA60 기울기 ≥ -0.5%
        2. downtrend: MA20 < MA60  AND  종가 < MA20  AND  MA60 기울기 ≤ -1.0%
        3. sideways : 위 두 조건 모두 불충족

    Args:
        weekly_df: week_start_date, open, high, low, close, volume 컬럼을 가진 주봉 DataFrame.
                   최소 (_MA_SLOW + _SLOPE_WINDOW) 행이 필요. 부족 시 'sideways' 반환.

    Returns:
        WeeklyTrend 인스턴스.
    """
    df = weekly_df.copy().reset_index(drop=True)

    if len(df) < _MIN_ROWS:
        return WeeklyTrend(
            direction="sideways",
            strength=0.0,
            ma20_above_ma60=False,
            price_above_ma20=False,
            ma60_slope=0.0,
            details={"reason": f"데이터 부족 ({len(df)} < {_MIN_ROWS})"},
        )

    close = df["close"]
    ma20 = sma(close, _MA_FAST)
    ma60 = sma(close, _MA_SLOW)

    last_close = float(close.iloc[-1])
    last_ma20 = float(ma20.iloc[-1])
    last_ma60 = float(ma60.iloc[-1])

    if pd.isna(last_ma20) or pd.isna(last_ma60):
        return WeeklyTrend(
            direction="sideways",
            strength=0.0,
            ma20_above_ma60=False,
            price_above_ma20=False,
            ma60_slope=0.0,
            details={"reason": "MA 값 NaN"},
        )

    ma20_above_ma60 = last_ma20 > last_ma60
    price_above_ma20 = last_close > last_ma20
    ma60_slope = _calc_slope_pct(ma60, _SLOPE_WINDOW)
    strength = (last_close - last_ma20) / last_ma20 * 100 if last_ma20 != 0 else 0.0

    details: dict[str, Any] = {
        "close": last_close,
        "ma20": round(last_ma20, 4),
        "ma60": round(last_ma60, 4),
        "ma60_slope_pct": round(ma60_slope * 100, 4),
        "rows": len(df),
    }

    if ma20_above_ma60 and price_above_ma20 and ma60_slope >= _UPTREND_SLOPE_MIN:
        direction: TrendDirection = "uptrend"
    elif not ma20_above_ma60 and not price_above_ma20 and ma60_slope <= _DOWNTREND_SLOPE_MAX:
        direction = "downtrend"
    else:
        direction = "sideways"

    return WeeklyTrend(
        direction=direction,
        strength=round(strength, 4),
        ma20_above_ma60=ma20_above_ma60,
        price_above_ma20=price_above_ma20,
        ma60_slope=round(ma60_slope, 6),
        details=details,
    )
