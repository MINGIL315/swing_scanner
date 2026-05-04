"""이동평균선 계산 및 정배열 판정."""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """단순 이동평균 (Simple Moving Average).

    Args:
        series: 종가 시계열.
        period: 이동평균 기간 (일).

    Returns:
        동일 인덱스의 SMA 시리즈. 데이터 부족 구간은 NaN.
    """
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """지수 이동평균 (Exponential Moving Average).

    Args:
        series: 종가 시계열.
        period: span 파라미터 (α = 2 / (period + 1)).

    Returns:
        동일 인덱스의 EMA 시리즈.
    """
    return series.ewm(span=period, adjust=False).mean()


def add_moving_averages(
    df: pd.DataFrame,
    periods: list[int] | None = None,
    price_col: str = "close",
) -> pd.DataFrame:
    """DataFrame에 SMA 컬럼을 추가해 반환한다.

    Args:
        df        : OHLCV DataFrame (close 컬럼 필요).
        periods   : 계산할 기간 목록. 기본값 [5, 20, 60, 120].
        price_col : 기준 가격 컬럼명.

    Returns:
        ma_5, ma_20, ma_60, ma_120 컬럼이 추가된 복사본.
    """
    if periods is None:
        periods = [5, 20, 60, 120]

    result = df.copy()
    for p in periods:
        result[f"ma_{p}"] = sma(result[price_col], p)
    return result


def is_bullish_alignment(row: pd.Series) -> bool:
    """일봉 정배열 판정: ma_5 > ma_20 > ma_60.

    ma_120 이 있으면 ma_60 > ma_120 도 함께 확인한다.
    어느 값이라도 NaN 이면 False.

    Args:
        row: DataFrame 의 단일 행 (ma_5, ma_20, ma_60 필수).

    Returns:
        정배열이면 True.
    """
    try:
        v5, v20, v60 = float(row["ma_5"]), float(row["ma_20"]), float(row["ma_60"])
    except (KeyError, TypeError, ValueError):
        return False

    if any(pd.isna(x) for x in (v5, v20, v60)):
        return False

    if not (v5 > v20 > v60):
        return False

    # ma_120 이 있고 유효한 경우 추가 확인
    if "ma_120" in row.index:
        v120 = row["ma_120"]
        if not pd.isna(v120) and float(v120) >= v60:
            return False

    return True


def is_bearish_alignment(row: pd.Series) -> bool:
    """역배열 판정: ma_5 < ma_20 < ma_60.

    Args:
        row: DataFrame 의 단일 행.

    Returns:
        역배열이면 True.
    """
    try:
        v5, v20, v60 = float(row["ma_5"]), float(row["ma_20"]), float(row["ma_60"])
    except (KeyError, TypeError, ValueError):
        return False

    if any(pd.isna(x) for x in (v5, v20, v60)):
        return False

    return v5 < v20 < v60
