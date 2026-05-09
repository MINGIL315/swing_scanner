"""ATR (Average True Range) 변동성 지표 — Wilder 표준."""
from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR (Average True Range).

    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR        = Wilder's EMA (alpha = 1 / period)

    Args:
        df    : OHLCV DataFrame (high, low, close 컬럼 필수).
        period: ATR 기간 (기본 14).

    Returns:
        동일 인덱스의 ATR 시리즈. 첫 period-1 행은 NaN (min_periods=period).
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
