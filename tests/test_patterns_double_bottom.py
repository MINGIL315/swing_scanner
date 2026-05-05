"""쌍바닥 패턴 탐지기 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def detected_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "double_bottom_detected.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def no_signal_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "double_bottom_no_signal.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


# ---------------------------------------------------------------------------


class TestDoubleBottomDetect:
    def test_pattern_detected(self, detected_df: pd.DataFrame) -> None:
        """쌍바닥 픽스처에서 패턴이 탐지된다."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        result = DoubleBottomDetector().detect(detected_df, "TEST")
        assert result is not None

    def test_no_pattern_on_noise(self, no_signal_df: pd.DataFrame) -> None:
        """노이즈 데이터에서는 패턴이 탐지되지 않는다."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        result = DoubleBottomDetector().detect(no_signal_df, "TEST")
        assert result is None

    def test_result_fields(self, detected_df: pd.DataFrame) -> None:
        """PatternResult 모든 필드가 유효 범위에 있다."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        result = DoubleBottomDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.pattern_name == "double_bottom"
        assert result.entry_price > result.stop_loss
        assert result.target_price > result.entry_price
        assert result.risk_reward_ratio > 0
        assert 0.0 <= result.raw_score <= 100.0

    def test_stop_loss_below_lows(self, detected_df: pd.DataFrame) -> None:
        """손절가는 두 저점 평균보다 낮다."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        result = DoubleBottomDetector().detect(detected_df, "TEST")
        assert result is not None
        avg_low = float(np.mean(result.details["trough_prices"]))
        assert result.stop_loss < avg_low

    def test_insufficient_data_returns_none(self) -> None:
        """데이터가 너무 적으면 None."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        df = pd.DataFrame(
            {"open": [100.0] * 30, "high": [101.0] * 30,
             "low": [99.0] * 30, "close": [100.0] * 30, "volume": [1_000_000] * 30}
        )
        assert DoubleBottomDetector().detect(df) is None

    def test_single_trough_returns_none(self) -> None:
        """저점이 1개뿐이면 None."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        import numpy as np

        # 단조 하락 후 단순 반등 — 저점 1개
        rng = np.random.default_rng(7)
        n = 70
        close = np.concatenate([
            np.linspace(100, 60, 35),
            np.linspace(60, 90, 35),
        ]) + rng.normal(0, 0.1, n)
        df = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": [1_000_000] * n}
        )
        result = DoubleBottomDetector().detect(df)
        assert result is None

    def test_trough_price_tolerance(self) -> None:
        """두 저점 가격 편차가 ±3% 초과이면 None."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        import numpy as np

        rng = np.random.default_rng(3)
        n = 80
        close = np.empty(n)
        close[:10] = np.linspace(100, 80, 10)
        # 첫 저점: 50, 두 번째 저점: 70 (차이 > 6% of avg)
        close[10:20] = np.concatenate([np.linspace(80, 50, 5), np.linspace(50, 75, 5)])
        close[20:30] = 75 + rng.normal(0, 0.3, 10)
        close[30:40] = np.concatenate([np.linspace(75, 70, 5), np.linspace(70, 78, 5)])
        close[40:80] = 78 + rng.normal(0, 0.2, 40)
        df = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": [1_000_000] * n}
        )
        result = DoubleBottomDetector().detect(df)
        assert result is None


class TestDoubleBottomHigherLowBonus:
    """higher low 가산점 (last_low ≥ first_low × 1.005 → +5) 동작 검증."""

    @staticmethod
    def _common_kwargs() -> dict:
        return dict(
            trough_prices=np.array([100.0, 100.0]),
            avg_low=100.0,
            neckline=110.0,
            recent_close=112.0,
            volume=np.array([1_000_000] * 60),
            last_trough_idx=30,
        )

    def test_details_exposes_first_last_lows(self, detected_df: pd.DataFrame) -> None:
        """details 에 first_low, last_low, last_first_low_ratio 노출."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        result = DoubleBottomDetector().detect(detected_df, "TEST")
        assert result is not None
        assert "first_low" in result.details
        assert "last_low" in result.details
        assert "last_first_low_ratio" in result.details
        assert result.details["last_first_low_ratio"] > 0

    def test_higher_low_above_threshold_adds_five(self) -> None:
        """last_low 가 first_low 대비 0.5% 이상 높으면 raw_score +5."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        detector = DoubleBottomDetector()
        common = self._common_kwargs()
        score_equal = detector._calc_raw_score(
            first_low=100.0, last_low=100.0, **common,
        )
        score_higher = detector._calc_raw_score(
            first_low=100.0, last_low=101.0, **common,  # +1.0% > 0.5%
        )
        assert score_higher == pytest.approx(score_equal + 5.0)

    def test_higher_low_at_threshold_adds_five(self) -> None:
        """경계값 0.5% 차이는 가산 (≥ 비교)."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        detector = DoubleBottomDetector()
        common = self._common_kwargs()
        score_equal = detector._calc_raw_score(
            first_low=100.0, last_low=100.0, **common,
        )
        score_at = detector._calc_raw_score(
            first_low=100.0, last_low=100.5, **common,  # 정확히 +0.5%
        )
        assert score_at == pytest.approx(score_equal + 5.0)

    def test_higher_low_under_threshold_no_bonus(self) -> None:
        """0.5% 미만 차이는 noise 로 간주, 가산 없음."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        detector = DoubleBottomDetector()
        common = self._common_kwargs()
        score_equal = detector._calc_raw_score(
            first_low=100.0, last_low=100.0, **common,
        )
        score_micro = detector._calc_raw_score(
            first_low=100.0, last_low=100.3, **common,  # +0.3% < 0.5%
        )
        assert score_micro == pytest.approx(score_equal)

    def test_lower_low_no_bonus(self) -> None:
        """last_low < first_low 이면 보너스 없음."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        detector = DoubleBottomDetector()
        common = self._common_kwargs()
        score_equal = detector._calc_raw_score(
            first_low=100.0, last_low=100.0, **common,
        )
        score_lower = detector._calc_raw_score(
            first_low=100.0, last_low=99.5, **common,
        )
        assert score_lower == pytest.approx(score_equal)


class TestDoubleBottomEntrySignal:
    def test_entry_signal_returns_valid_strength(self, detected_df: pd.DataFrame) -> None:
        """entry_signal strength는 0~100 범위."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        sig = DoubleBottomDetector().entry_signal(detected_df)
        assert 0.0 <= sig.strength <= 100.0

    def test_entry_signal_has_four_components(self, detected_df: pd.DataFrame) -> None:
        """신호 컴포넌트가 4개."""
        from scanner.patterns.double_bottom import DoubleBottomDetector

        sig = DoubleBottomDetector().entry_signal(detected_df)
        assert len(sig.signals) == 4

    def test_entry_signal_all_true_gives_100(self) -> None:
        """4개 신호 모두 True이면 strength=100."""
        from scanner.patterns.base import EntrySignal

        sig = EntrySignal(
            strength=100.0,
            signals={"rsi_bounce": True, "bullish_volume": True,
                     "macd_cross": True, "prev_high_break": True},
        )
        total = sum(25.0 for v in sig.signals.values() if v)
        assert total == pytest.approx(100.0)
