"""주봉 추세 판정 모듈."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from scanner.kr.indicators.moving_average import sma

TrendDirection = Literal["uptrend", "downtrend", "sideways", "insufficient_data"]

# ── 추세 판정 파라미터 ──────────────────────────────────────────────
_MA_FAST: int = 20                      # 단기 이동평균 (주)
_MA_SLOW: int = 60                      # 장기 이동평균 (주)
_SLOPE_WINDOW: int = 8                  # MA60 기울기 산출 구간 (주)

# slope는 "윈도우 구간 동안의 누적 % 변화"로 정의됨
_UPTREND_SLOPE_MIN: float = -0.01       # 8주 누적 -1% 이상이면 상승 인정
_DOWNTREND_SLOPE_MAX: float = -0.02     # 8주 누적 -2% 이하면 하락 인정

_MIN_ROWS: int = _MA_SLOW + _SLOPE_WINDOW


@dataclass
class WeeklyTrend:
    """주봉 추세 판정 결과.

    Attributes:
        direction         : 'uptrend' | 'downtrend' | 'sideways' | 'insufficient_data'.
        strength          : 추세 강도. (MA20 - MA60) / MA60 × 100 (%).
                            양수=정배열 폭, 음수=역배열 폭. 절댓값이 클수록 추세 진행도 높음.
        ma20_above_ma60   : MA20 > MA60 (정배열 여부).
        price_above_ma20  : 종가 > MA20 (가격이 단기선 위인지).
        ma60_slope_pct    : MA60의 _SLOPE_WINDOW 구간 누적 변화율 (%).
        details           : 디버깅용 수치 원본.
    """

    direction: TrendDirection
    strength: float
    ma20_above_ma60: bool
    price_above_ma20: bool
    ma60_slope_pct: float
    details: dict[str, Any] = field(default_factory=dict)


def _calc_slope_pct(series: pd.Series, window: int) -> float:
    """시계열 마지막 window 구간의 누적 변화율(%)을 OLS로 계산.

    반환값은 "윈도우 동안 총 몇 % 변했는가"를 의미.
    예: 0.02 → 8주간 +2%, -0.01 → 8주간 -1%.
    """
    s = series.dropna()
    if len(s) < window:
        return 0.0

    tail = s.iloc[-window:]
    x = np.arange(len(tail), dtype=float)
    y = tail.to_numpy(dtype=float)

    x_mean, y_mean = x.mean(), y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0 or y_mean == 0:
        return 0.0

    slope_per_step = ((x - x_mean) * (y - y_mean)).sum() / denom
    total_change = slope_per_step * (len(tail) - 1)  # 윈도우 전체 변화량
    return float(total_change / y_mean)              # 평균값 기준 % (outlier 영향 감소)


def _empty_result(direction: TrendDirection, reason: str, rows: int) -> WeeklyTrend:
    """판정 불가 시 기본 결과."""
    return WeeklyTrend(
        direction=direction,
        strength=0.0,
        ma20_above_ma60=False,
        price_above_ma20=False,
        ma60_slope_pct=0.0,
        details={"reason": reason, "rows": rows},
    )


def detect_weekly_trend(weekly_df: pd.DataFrame) -> WeeklyTrend:
    """주봉 DataFrame에서 추세 방향과 강도를 판정.

    판정 규칙:
        uptrend  : 정배열 AND 종가>MA20 AND MA60 기울기 ≥ -1% (8주 누적)
        downtrend: 역배열 AND 종가<MA20 AND MA60 기울기 ≤ -2% (8주 누적)
        sideways : 위 두 조건 모두 불충족
        insufficient_data: 데이터 행 수 부족 또는 MA NaN

    Args:
        weekly_df: open, high, low, close 컬럼을 가진 주봉 DataFrame.
                   최소 _MIN_ROWS 행 필요. 미완성 마지막 주봉은 호출 전에
                   _resample_weekly() 단계에서 제거되어야 한다.
    """
    rows = len(weekly_df)
    if rows < _MIN_ROWS:
        return _empty_result(
            "insufficient_data", f"데이터 부족 ({rows} < {_MIN_ROWS})", rows
        )

    close = weekly_df["close"]

    ma20 = sma(close, _MA_FAST)
    ma60 = sma(close, _MA_SLOW)

    last_close = float(close.iloc[-1])
    last_ma20 = float(ma20.iloc[-1])
    last_ma60 = float(ma60.iloc[-1])

    if pd.isna(last_ma20) or pd.isna(last_ma60) or last_ma60 == 0:
        return _empty_result("insufficient_data", "MA 값 NaN 또는 0", rows)

    # 3가지 핵심 신호
    ma20_above_ma60 = last_ma20 > last_ma60
    price_above_ma20 = last_close > last_ma20
    ma60_slope_pct = _calc_slope_pct(ma60, _SLOPE_WINDOW)

    # 추세 강도: 이평선 간격 (%) — 절댓값이 클수록 추세 진행도 높음
    strength = (last_ma20 - last_ma60) / last_ma60 * 100

    # 판정
    if (
        ma20_above_ma60
        and price_above_ma20
        and ma60_slope_pct >= _UPTREND_SLOPE_MIN
    ):
        direction: TrendDirection = "uptrend"
    elif (
        not ma20_above_ma60
        and not price_above_ma20
        and ma60_slope_pct <= _DOWNTREND_SLOPE_MAX
    ):
        direction = "downtrend"
    else:
        direction = "sideways"

    details: dict[str, Any] = {
        "close": last_close,
        "ma20": round(last_ma20, 4),
        "ma60": round(last_ma60, 4),
        "ma_gap_pct": round(strength, 4),
        "ma60_slope_pct": round(ma60_slope_pct * 100, 4),
        "price_to_ma20_pct": round((last_close - last_ma20) / last_ma20 * 100, 4),
        "rows": rows,
    }

    return WeeklyTrend(
        direction=direction,
        strength=round(strength, 4),
        ma20_above_ma60=ma20_above_ma60,
        price_above_ma20=price_above_ma20,
        ma60_slope_pct=round(ma60_slope_pct * 100, 4),
        details=details,
    )
