"""골든크로스 패턴 탐지기 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def detected_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "golden_cross_detected.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def no_signal_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "golden_cross_no_signal.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


# ---------------------------------------------------------------------------


class TestGoldenCrossDetect:
    def test_pattern_detected(self, detected_df: pd.DataFrame) -> None:
        """골든크로스 픽스처에서 패턴이 탐지된다."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        result = GoldenCrossDetector().detect(detected_df, "TEST")
        assert result is not None

    def test_no_pattern_on_steady_uptrend(self, no_signal_df: pd.DataFrame) -> None:
        """MA20이 이미 MA60 위에서 지속 상승하면 None."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        result = GoldenCrossDetector().detect(no_signal_df, "TEST")
        assert result is None

    def test_result_fields(self, detected_df: pd.DataFrame) -> None:
        """PatternResult 필드가 유효 범위."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        result = GoldenCrossDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.pattern_name == "golden_cross"
        assert result.entry_price > result.stop_loss
        assert result.target_price > result.entry_price
        assert 0.0 <= result.raw_score <= 100.0

    def test_cross_recency(self, detected_df: pd.DataFrame) -> None:
        """크로스가 최근 5일 이내 발생."""
        from scanner.patterns.golden_cross import GoldenCrossDetector
        from scanner.config import GOLDEN_CROSS_RECENT_DAYS

        result = GoldenCrossDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["days_since_cross"] <= GOLDEN_CROSS_RECENT_DAYS

    def test_insufficient_data_returns_none(self) -> None:
        """데이터 부족 시 None."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        df = pd.DataFrame(
            {"open": [100.0] * 50, "high": [101.0] * 50,
             "low": [99.0] * 50, "close": [100.0] * 50, "volume": [1_000_000] * 50}
        )
        assert GoldenCrossDetector().detect(df) is None

    def test_cross_too_old_returns_none(self) -> None:
        """크로스가 5일 초과로 오래되면 None."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        rng = np.random.default_rng(77)
        n = 120
        close = np.empty(n)
        # 하락 후 반등, 단 마지막 10봉은 평탄 (크로스 후 오래됨)
        close[:60] = np.linspace(100, 80, 60) + rng.normal(0, 0.2, 60)
        close[60:100] = np.linspace(80, 115, 40) + rng.normal(0, 0.4, 40)
        close[100:] = 115 + rng.normal(0, 0.2, 20)
        volume = rng.integers(400_000, 800_000, n)
        df = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": volume}
        )
        result = GoldenCrossDetector().detect(df)
        # 크로스가 10봉 이상 전이므로 탐지 안 됨
        assert result is None

    def test_low_volume_returns_none(self) -> None:
        """거래량이 1.2배 미만이면 None."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        df = pd.read_csv(
            str(FIXTURE_DIR / "golden_cross_detected.csv"), parse_dates=["date"]
        )
        df["date"] = df["date"].dt.date
        # 모든 거래량을 균등하게 설정 (ratio=1.0)
        df["volume"] = 600_000
        result = GoldenCrossDetector().detect(df)
        assert result is None

    def test_steep_ma60_decline_returns_none(self) -> None:
        """MA60 급락(-1% 이상) 시 None."""
        from scanner.patterns.golden_cross import GoldenCrossDetector

        rng = np.random.default_rng(33)
        n = 110
        # 가파른 하락 후 단기 반등 (MA60 여전히 급락)
        close = np.concatenate([
            np.linspace(100, 60, 85),
            np.linspace(60, 85, 25),
        ]) + rng.normal(0, 0.3, n)
        volume = rng.integers(400_000, 2_000_000, n)
        df = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": volume}
        )
        result = GoldenCrossDetector().detect(df)
        assert result is None


class TestGoldenCrossEntrySignal:
    def test_entry_signal_returns_valid_strength(self, detected_df: pd.DataFrame) -> None:
        from scanner.patterns.golden_cross import GoldenCrossDetector

        sig = GoldenCrossDetector().entry_signal(detected_df)
        assert 0.0 <= sig.strength <= 100.0

    def test_entry_signal_has_four_components(self, detected_df: pd.DataFrame) -> None:
        from scanner.patterns.golden_cross import GoldenCrossDetector

        sig = GoldenCrossDetector().entry_signal(detected_df)
        assert len(sig.signals) == 4
