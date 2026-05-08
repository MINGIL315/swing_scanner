"""거래량 필터 단위 테스트."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.config import (
    LIQUIDITY_LOOKBACK_DAYS,
    MIN_AVG_TRADING_VALUE_KRW,
    MIN_AVG_TRADING_VALUE_USD,
)
from scanner.kr.filtering.volume_filter import _get_value_series, passes_volume_filter


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_df(
    n: int = 30,
    close: float = 50_000.0,
    volume: int = 200_000,
    value: float | None = None,
    increasing_volume: bool = True,
) -> pd.DataFrame:
    """테스트용 일봉 DataFrame 생성."""
    rng = np.random.default_rng(0)
    closes = np.full(n, close) + rng.normal(0, 10, n)
    highs = closes + 100
    lows = closes - 100
    if increasing_volume:
        # 후반부 거래량이 더 많음 → 최근 5일 > 20일 평균
        vols = np.concatenate([
            np.full(n - 5, int(volume * 0.8)),
            np.full(5, int(volume * 1.5)),
        ])
    else:
        vols = np.full(n, volume)

    df = pd.DataFrame({
        "open": closes - 50,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols.astype(float),
    })
    if value is not None:
        df["value"] = float(value)
    return df


# ---------------------------------------------------------------------------
# KR 필터 테스트
# ---------------------------------------------------------------------------

class TestVolumeFilterKR:
    def test_passes_with_sufficient_value_and_rising_volume(self) -> None:
        """거래대금 충분 + 거래량 상승 → True."""
        # 50억원 이상을 만족하는 value
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_KRW + 1e9, increasing_volume=True)
        passed, details = passes_volume_filter(df, "KR")
        assert passed is True
        assert details["ok_value"] is True
        assert details["ok_volume_trend"] is True

    def test_fails_with_low_value(self) -> None:
        """거래대금 미달 → False."""
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_KRW * 0.1, increasing_volume=True)
        passed, details = passes_volume_filter(df, "KR")
        assert passed is False
        assert details["ok_value"] is False

    def test_fails_with_flat_volume(self) -> None:
        """거래량이 균등(최근 5일 ≤ 20일 평균) → ok_volume_trend=False."""
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_KRW + 1e9, increasing_volume=False)
        passed, details = passes_volume_filter(df, "KR")
        assert details["ok_volume_trend"] is False
        assert passed is False

    def test_details_keys_present(self) -> None:
        """details 딕셔너리에 필수 키가 모두 있다."""
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_KRW + 1e9, increasing_volume=True)
        _, details = passes_volume_filter(df, "KR")
        for key in ("avg_value", "threshold", "ok_value", "recent_vol", "base_vol", "ok_volume_trend"):
            assert key in details

    def test_threshold_is_kr(self) -> None:
        df = _make_df(n=25, value=MIN_AVG_TRADING_VALUE_KRW + 1, increasing_volume=True)
        _, details = passes_volume_filter(df, "KR")
        assert details["threshold"] == MIN_AVG_TRADING_VALUE_KRW


# ---------------------------------------------------------------------------
# US 필터 테스트
# ---------------------------------------------------------------------------

class TestVolumeFilterUS:
    def test_passes_us_with_sufficient_value(self) -> None:
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_USD + 1e6, increasing_volume=True)
        passed, details = passes_volume_filter(df, "US")
        assert passed is True

    def test_fails_us_with_low_value(self) -> None:
        df = _make_df(n=30, value=MIN_AVG_TRADING_VALUE_USD * 0.1, increasing_volume=True)
        passed, _ = passes_volume_filter(df, "US")
        assert passed is False

    def test_threshold_is_us(self) -> None:
        df = _make_df(n=25, value=MIN_AVG_TRADING_VALUE_USD + 1, increasing_volume=True)
        _, details = passes_volume_filter(df, "US")
        assert details["threshold"] == MIN_AVG_TRADING_VALUE_USD


# ---------------------------------------------------------------------------
# Typical Price fallback 테스트
# ---------------------------------------------------------------------------

class TestGetValueSeries:
    def test_uses_value_column_when_present(self) -> None:
        """value 컬럼이 있으면 그것을 반환한다."""
        df = _make_df(n=25, value=1_000_000.0)
        series = _get_value_series(df)
        assert float(series.iloc[-1]) == pytest.approx(1_000_000.0)

    def test_typical_price_fallback(self) -> None:
        """value 컬럼 없으면 Typical Price × volume 을 반환한다."""
        df = _make_df(n=25)  # value 컬럼 없음
        series = _get_value_series(df)
        expected = (df["high"] + df["low"] + df["close"]) / 3.0 * df["volume"]
        pd.testing.assert_series_equal(series.reset_index(drop=True),
                                       expected.reset_index(drop=True))

    def test_passes_filter_with_typical_price(self) -> None:
        """value 없이도 Typical Price fallback으로 필터 통과 가능."""
        # close=50000, volume=80000 → TP≈50000, value≈40억 < 50억 → ok_value=False
        df = _make_df(n=25, close=50_000.0, volume=80_000, increasing_volume=True)
        passed, details = passes_volume_filter(df, "KR")
        assert details["ok_value"] is False

    def test_high_price_stock_passes_with_typical_price(self) -> None:
        """고가 종목은 Typical Price fallback으로 KR 기준 통과."""
        # 50000 × 150000 = 75억 > 50억
        df = _make_df(n=25, close=50_000.0, volume=150_000, increasing_volume=True)
        # value 컬럼 없음 → TP fallback
        passed, details = passes_volume_filter(df, "KR")
        assert details["ok_value"] is True
