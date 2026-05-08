"""눌림목 패턴 탐지기 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def detected_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "pullback_detected.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def no_signal_df() -> pd.DataFrame:
    path = FIXTURE_DIR / "pullback_no_signal.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


# ---------------------------------------------------------------------------


class TestPullbackDetect:
    def test_pattern_detected(self, detected_df: pd.DataFrame) -> None:
        """눌림목 픽스처에서 패턴이 탐지된다."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(detected_df, "TEST")
        assert result is not None

    def test_no_pattern_on_downtrend(self, no_signal_df: pd.DataFrame) -> None:
        """하락 추세에서는 패턴이 탐지되지 않는다."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(no_signal_df, "TEST")
        assert result is None

    def test_result_fields(self, detected_df: pd.DataFrame) -> None:
        """PatternResult 모든 필드가 유효 범위에 있다."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.pattern_name == "pullback"
        assert result.entry_price > result.stop_loss
        assert result.target_price > result.entry_price
        assert 0.0 <= result.raw_score <= 100.0

    def test_weekly_trend_is_uptrend(self, detected_df: pd.DataFrame) -> None:
        """탐지된 결과의 주봉 추세가 uptrend이다."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["weekly_trend"] == "uptrend"

    def test_ma_alignment(self, detected_df: pd.DataFrame) -> None:
        """MA 정배열: MA5 > MA20 > MA60."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["ma5"] > result.details["ma20"]
        assert result.details["ma20"] > result.details["ma60"]

    def test_price_near_ma(self, detected_df: pd.DataFrame) -> None:
        """현재가가 MA20 또는 MA60 근처에 위치."""
        from scanner.kr.patterns.pullback import PullbackDetector

        result = PullbackDetector().detect(detected_df, "TEST")
        assert result is not None
        assert result.details["near_ma20"] or result.details["near_ma60"]

    def test_insufficient_data_returns_none(self) -> None:
        """데이터 부족 시 None."""
        from scanner.kr.patterns.pullback import PullbackDetector

        df = pd.DataFrame(
            {"open": [100.0] * 200, "high": [101.0] * 200,
             "low": [99.0] * 200, "close": [100.0] * 200, "volume": [1_000_000] * 200}
        )
        assert PullbackDetector().detect(df) is None

    def test_bearish_candle_returns_none(self) -> None:
        """마지막 봉이 음봉이면 None."""
        from scanner.kr.patterns.pullback import PullbackDetector

        df = pd.read_csv(
            str(FIXTURE_DIR / "pullback_detected.csv"), parse_dates=["date"]
        )
        df["date"] = df["date"].dt.date
        # 마지막 캔들을 음봉으로 변경
        df.loc[df.index[-1], "open"] = df["close"].iloc[-1] + 2.0
        result = PullbackDetector().detect(df)
        assert result is None

    def test_low_volume_returns_none(self) -> None:
        """거래량 부족 시 None."""
        from scanner.kr.patterns.pullback import PullbackDetector

        df = pd.read_csv(
            str(FIXTURE_DIR / "pullback_detected.csv"), parse_dates=["date"]
        )
        df["date"] = df["date"].dt.date
        # 모든 거래량을 동일하게 → 마지막 봉이 평균 이하
        df["volume"] = 500_000
        result = PullbackDetector().detect(df)
        assert result is None

    def test_no_ma_alignment_returns_none(self) -> None:
        """MA 역배열 데이터에서 None."""
        from scanner.kr.patterns.pullback import PullbackDetector

        rng = np.random.default_rng(13)
        n = 450
        # 하락 후 단기 반등 → MA5 아래에 MA20이 있는 역배열
        close = np.concatenate([
            np.linspace(160, 100, 400),
            np.linspace(100, 120, 50),
        ]) + rng.normal(0, 0.3, n)
        high = close + 0.5
        low = close - 0.5
        open_ = close - 0.3
        volume = rng.integers(400_000, 600_000, n)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "date": [d.date() for d in dates],
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        })
        result = PullbackDetector().detect(df)
        assert result is None


class TestPullbackEntrySignal:
    def test_entry_signal_returns_valid_strength(self, detected_df: pd.DataFrame) -> None:
        """entry_signal strength는 0~100 범위."""
        from scanner.kr.patterns.pullback import PullbackDetector

        sig = PullbackDetector().entry_signal(detected_df)
        assert 0.0 <= sig.strength <= 100.0

    def test_entry_signal_has_four_components(self, detected_df: pd.DataFrame) -> None:
        """신호 컴포넌트가 4개."""
        from scanner.kr.patterns.pullback import PullbackDetector

        sig = PullbackDetector().entry_signal(detected_df)
        assert len(sig.signals) == 4
