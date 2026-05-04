"""RSI (Relative Strength Index) 계산."""
from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI를 계산한다.

    표준 RSI 공식: RS = avg_gain / avg_loss (Wilder's smoothing).
    pandas rolling mean 방식이 아닌 EWM(alpha=1/period, adjust=False) 을 사용한다.

    Args:
        close : 종가 시계열.
        period: RSI 기간. 기본 14.

    Returns:
        0 ~ 100 범위의 RSI 시리즈. 초기 구간은 NaN.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's smoothing = EWM com = period - 1
    avg_gain = gain.ewm(com=period - 1, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def is_oversold(rsi_value: float, threshold: float = 30.0) -> bool:
    """RSI 과매도 판정 (기본 30 이하).

    Args:
        rsi_value : 단일 RSI 값.
        threshold : 과매도 기준선.

    Returns:
        과매도면 True.
    """
    return float(rsi_value) <= threshold


def is_overbought(rsi_value: float, threshold: float = 70.0) -> bool:
    """RSI 과매수 판정 (기본 70 이상).

    Args:
        rsi_value : 단일 RSI 값.
        threshold : 과매수 기준선.

    Returns:
        과매수면 True.
    """
    return float(rsi_value) >= threshold
