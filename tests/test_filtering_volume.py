"""거래량 모멘텀 필터 단위 테스트 (CLAUDE.md §7)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.us.filtering.volume_filter import passes_volume_filter


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _make_df(
    n: int = 30,
    close: float = 50_000.0,
    volume: int = 200_000,
    increasing_volume: bool = True,
) -> pd.DataFrame:
    """테스트용 일봉 DataFrame 생성."""
    rng = np.random.default_rng(0)
    closes = np.full(n, close) + rng.normal(0, 10, n)
    if increasing_volume:
        # 후반부 거래량이 더 많음 → 최근 5일 > 20일 평균
        vols = np.concatenate([
            np.full(n - 5, int(volume * 0.8)),
            np.full(5, int(volume * 1.5)),
        ])
    else:
        vols = np.full(n, volume)

    return pd.DataFrame({
        "open": closes - 50,
        "high": closes + 100,
        "low": closes - 100,
        "close": closes,
        "volume": vols.astype(float),
    })


# ---------------------------------------------------------------------------
# KR 필터 테스트
# ---------------------------------------------------------------------------


class TestVolumeFilterKR:
    def test_passes_with_rising_volume(self) -> None:
        """최근 5일 거래량 > 20일 평균 → True."""
        df = _make_df(n=30, increasing_volume=True)
        passed, details = passes_volume_filter(df, "KR")
        assert passed is True
        assert details["ok_volume_trend"] is True

    def test_fails_with_flat_volume(self) -> None:
        """거래량이 균등(최근 5일 ≤ 20일 평균) → False."""
        df = _make_df(n=30, increasing_volume=False)
        passed, details = passes_volume_filter(df, "KR")
        assert passed is False
        assert details["ok_volume_trend"] is False

    def test_details_keys_present(self) -> None:
        """details 에 필수 키가 모두 있고, 폐기된 키는 없다."""
        df = _make_df(n=30, increasing_volume=True)
        _, details = passes_volume_filter(df, "KR")
        for key in ("recent_vol", "base_vol", "ok_volume_trend", "passed"):
            assert key in details
        for key in ("avg_value", "threshold", "ok_value"):
            assert key not in details

    def test_short_history_returns_false(self) -> None:
        """RECENT_VOLUME_LOOKBACK_DAYS+1 행 미만이면 False."""
        df = _make_df(n=3, increasing_volume=False)  # increasing_volume 은 n>=5 일 때만 의미
        passed, details = passes_volume_filter(df, "KR")
        assert passed is False
        assert details["ok_volume_trend"] is False


# ---------------------------------------------------------------------------
# US 필터 테스트 (KR 과 동일 동작)
# ---------------------------------------------------------------------------


class TestVolumeFilterUS:
    def test_passes_us_with_rising_volume(self) -> None:
        df = _make_df(n=30, increasing_volume=True)
        passed, _ = passes_volume_filter(df, "US")
        assert passed is True

    def test_fails_us_with_flat_volume(self) -> None:
        df = _make_df(n=30, increasing_volume=False)
        passed, _ = passes_volume_filter(df, "US")
        assert passed is False
