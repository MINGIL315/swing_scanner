"""박스권 돌파 패턴 탐지기 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def detected_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "box_breakout_detected.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def no_signal_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "box_breakout_no_signal.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


# ---------------------------------------------------------------------------


class TestBoxBreakoutDetect:
    def test_pattern_detected(self, detected_df: pd.DataFrame) -> None:
        """박스권 돌파 픽스처에서 패턴이 탐지된다."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        result = BoxBreakoutDetector().detect(detected_df, "TEST")
        assert result is not None

    def test_no_pattern_on_trend(self, no_signal_df: pd.DataFrame) -> None:
        """추세 상승 데이터에서는 패턴이 탐지되지 않는다."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        result = BoxBreakoutDetector().detect(no_signal_df, "TEST")
        assert result is None

    def test_result_fields(self, detected_df: pd.DataFrame) -> None:
        """PatternResult 모든 필드가 유효 범위에 있다."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        result = BoxBreakoutDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.pattern_name == "box_breakout"
        assert result.entry_price > result.stop_loss
        assert result.target_price > result.entry_price
        assert 0.0 <= result.raw_score <= 100.0

    def test_box_range_within_threshold(self, detected_df: pd.DataFrame) -> None:
        """박스 폭이 10% 이내."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector
        from scanner.config import BOX_BREAKOUT_RANGE_PCT

        result = BoxBreakoutDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["range_pct"] <= BOX_BREAKOUT_RANGE_PCT * 100

    def test_vol_ratio_above_threshold(self, detected_df: pd.DataFrame) -> None:
        """돌파일 거래량 비율이 1.5 이상."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector
        from scanner.config import BOX_BREAKOUT_VOLUME_RATIO

        result = BoxBreakoutDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["vol_ratio_at_break"] >= BOX_BREAKOUT_VOLUME_RATIO

    def test_insufficient_data_returns_none(self) -> None:
        """데이터 부족 시 None."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        df = pd.DataFrame(
            {"open": [100.0] * 50, "high": [101.0] * 50,
             "low": [99.0] * 50, "close": [100.0] * 50, "volume": [1_000_000] * 50}
        )
        assert BoxBreakoutDetector().detect(df) is None

    def test_wide_range_returns_none(self) -> None:
        """박스 폭이 10% 초과이면 None."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        rng = np.random.default_rng(10)
        n = 70
        # 30% 범위 내 큰 진폭 횡보 → range_pct > 10%
        close = 100 + rng.uniform(-15, 15, n)
        high = close + rng.uniform(0.5, 1.5, n)
        low = close - rng.uniform(0.5, 1.5, n)
        volume = rng.integers(400_000, 600_000, n)
        df = pd.DataFrame(
            {"open": close, "high": high, "low": low, "close": close, "volume": volume}
        )
        result = BoxBreakoutDetector().detect(df)
        assert result is None

    def test_no_breakout_returns_none(self) -> None:
        """박스권은 형성되나 돌파가 없으면 None."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        rng = np.random.default_rng(20)
        n = 70
        # 타이트한 박스 유지, 돌파 없음
        close = 100 + rng.uniform(-2, 2, n)
        high = close + 0.5
        low = close - 0.5
        volume = rng.integers(400_000, 600_000, n)
        df = pd.DataFrame(
            {"open": close, "high": high, "low": low, "close": close, "volume": volume}
        )
        result = BoxBreakoutDetector().detect(df)
        assert result is None

    def test_low_volume_at_breakout_returns_none(self) -> None:
        """돌파 거래량 비율이 1.5 미만이면 None."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        df = pd.read_csv(
            str(FIXTURE_DIR / "box_breakout_detected.csv"), parse_dates=["date"]
        )
        df["date"] = df["date"].dt.date
        # 모든 거래량을 균등하게 → ratio ≈ 1.0
        df["volume"] = 500_000
        result = BoxBreakoutDetector().detect(df)
        assert result is None


class TestBoxBreakoutEntrySignal:
    def test_entry_signal_returns_valid_strength(self, detected_df: pd.DataFrame) -> None:
        """entry_signal strength는 0~100 범위."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        sig = BoxBreakoutDetector().entry_signal(detected_df)
        assert 0.0 <= sig.strength <= 100.0

    def test_entry_signal_has_four_components(self, detected_df: pd.DataFrame) -> None:
        """신호 컴포넌트가 4개."""
        from scanner.us.patterns.box_breakout import BoxBreakoutDetector

        sig = BoxBreakoutDetector().entry_signal(detected_df)
        assert len(sig.signals) == 4
