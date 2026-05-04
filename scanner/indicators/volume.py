"""거래량·거래대금 분석 지표."""
from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """현재 거래량 / 직전 period일 평균 거래량 비율을 반환한다.

    Args:
        volume: 거래량 시계열.
        period: 평균 산출 기간 (기본 20).

    Returns:
        비율 시리즈. 평균이 0이거나 NaN이면 NaN.
    """
    avg = volume.rolling(window=period, min_periods=period).mean()
    return volume / avg.replace(0, float("nan"))


def value_ratio(value: pd.Series, period: int = 20) -> pd.Series:
    """현재 거래대금 / 직전 period일 평균 거래대금 비율을 반환한다.

    Args:
        value : 거래대금 시계열.
        period: 평균 산출 기간 (기본 20).

    Returns:
        비율 시리즈.
    """
    avg = value.rolling(window=period, min_periods=period).mean()
    return value / avg.replace(0, float("nan"))


def avg_value(value: pd.Series, period: int = 20) -> pd.Series:
    """직전 period일 평균 거래대금을 반환한다.

    유동성 필터(일평균 거래대금 50억 이상 등)에 사용한다.

    Args:
        value : 거래대금 시계열.
        period: 평균 산출 기간 (기본 20).

    Returns:
        평균 거래대금 시리즈.
    """
    return value.rolling(window=period, min_periods=period).mean()


def is_volume_surge(ratio_value: float, threshold: float = 1.5) -> bool:
    """거래량(또는 거래대금) 급등 여부를 판정한다.

    Args:
        ratio_value: volume_ratio / value_ratio 결과 단일 값.
        threshold  : 급등 기준 배율 (기본 1.5배).

    Returns:
        ratio_value >= threshold 이면 True.
    """
    if pd.isna(ratio_value):
        return False
    return float(ratio_value) >= threshold
