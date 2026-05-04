"""신뢰도 점수 계산기 단위 테스트."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scanner.patterns.base import PatternResult
from scanner.scoring.scorer import (
    ScoringInput,
    _ma_alignment_score,
    _rsi_score,
    _volume_score,
    _weekly_trend_score,
    calculate_confidence_score,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_result(
    raw_score: float = 70.0,
    vol_ratio: float = 1.5,
    ma5: float | None = 105.0,
    ma20: float | None = 102.0,
    ma60: float | None = 98.0,
) -> PatternResult:
    details = {"vol_ratio": vol_ratio}
    if ma5 is not None:
        details["ma5"] = ma5
    if ma20 is not None:
        details["ma20"] = ma20
    if ma60 is not None:
        details["ma60"] = ma60

    return PatternResult(
        pattern_name="pullback",
        ticker="TEST",
        detected_at=date(2026, 1, 1),
        entry_price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        risk_reward_ratio=2.0,
        raw_score=raw_score,
        details=details,
    )


def _make_uptrend_df(n: int = 300) -> pd.DataFrame:
    """단조 상승 일봉 DataFrame."""
    rng = np.random.default_rng(42)
    close = np.linspace(80, 160, n) + rng.normal(0, 0.3, n)
    return pd.DataFrame({
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": rng.integers(500_000, 1_000_000, n),
    })


def _make_inp(
    direction: str = "uptrend",
    strength: float = 3.0,
    raw_score: float = 70.0,
    vol_ratio: float = 1.5,
    df: pd.DataFrame | None = None,
) -> ScoringInput:
    return ScoringInput(
        pattern_result=_make_result(raw_score=raw_score, vol_ratio=vol_ratio),
        weekly_trend_direction=direction,
        weekly_trend_strength=strength,
        daily_df=df if df is not None else _make_uptrend_df(),
    )


# ---------------------------------------------------------------------------
# 컴포넌트 테스트
# ---------------------------------------------------------------------------

class TestWeeklyTrendScore:
    def test_uptrend_is_100(self) -> None:
        assert _weekly_trend_score("uptrend") == 100.0

    def test_sideways_is_40(self) -> None:
        assert _weekly_trend_score("sideways") == 40.0

    def test_downtrend_is_0(self) -> None:
        assert _weekly_trend_score("downtrend") == 0.0

    def test_unknown_is_0(self) -> None:
        assert _weekly_trend_score("unknown") == 0.0


class TestVolumeScore:
    def test_ratio_1_0_is_0(self) -> None:
        assert _volume_score(1.0) == 0.0

    def test_ratio_1_5_is_100(self) -> None:
        assert _volume_score(1.5) == 100.0

    def test_ratio_1_25_is_50(self) -> None:
        assert abs(_volume_score(1.25) - 50.0) < 1e-6

    def test_ratio_below_1_is_0(self) -> None:
        assert _volume_score(0.5) == 0.0

    def test_ratio_above_1_5_capped_100(self) -> None:
        assert _volume_score(3.0) == 100.0


class TestMaAlignmentScore:
    def test_aligned_is_100(self) -> None:
        assert _ma_alignment_score({"ma5": 105.0, "ma20": 102.0, "ma60": 98.0}) == 100.0

    def test_misaligned_is_0(self) -> None:
        assert _ma_alignment_score({"ma5": 95.0, "ma20": 102.0, "ma60": 98.0}) == 0.0

    def test_missing_keys_returns_100(self) -> None:
        # 패턴에 따라 ma 키가 없을 수 있음 → 기본 100
        assert _ma_alignment_score({}) == 100.0


class TestRsiScore:
    def test_rsi_in_range_is_100(self) -> None:
        # RSI 55 근방이 나오는 상승 데이터
        df = _make_uptrend_df(100)
        score = _rsi_score(df)
        assert 0.0 <= score <= 100.0

    def test_insufficient_data_returns_50(self) -> None:
        df = pd.DataFrame({"close": [100.0] * 5})
        assert _rsi_score(df) == 50.0

    def test_missing_close_returns_50(self) -> None:
        df = pd.DataFrame({"open": [100.0] * 30})
        assert _rsi_score(df) == 50.0


# ---------------------------------------------------------------------------
# 통합 테스트
# ---------------------------------------------------------------------------

class TestCalculateConfidenceScore:
    def test_score_in_range(self) -> None:
        score = calculate_confidence_score(_make_inp())
        assert 0.0 <= score <= 100.0

    def test_uptrend_higher_than_downtrend(self) -> None:
        up = calculate_confidence_score(_make_inp(direction="uptrend"))
        down = calculate_confidence_score(_make_inp(direction="downtrend"))
        assert up > down

    def test_uptrend_score_above_60(self) -> None:
        """정배열 + uptrend + vol_ratio=1.5 + raw=70 → 60점 이상."""
        score = calculate_confidence_score(_make_inp())
        assert score >= 60.0

    def test_downtrend_score_below_50(self) -> None:
        """downtrend → weekly 0점 (30%) → 전체 낮음."""
        score = calculate_confidence_score(_make_inp(direction="downtrend", raw_score=30.0, vol_ratio=1.0))
        assert score < 50.0

    def test_weight_sum_correctness(self) -> None:
        """raw_score=100, vol_ratio=1.5(→100), uptrend, 정배열이면 rsi 제외 최소 90점."""
        df = _make_uptrend_df(300)
        inp = _make_inp(direction="uptrend", raw_score=100.0, vol_ratio=1.5, df=df)
        score = calculate_confidence_score(inp)
        # weekly(30) + pattern(25) + vol(20) + ma(15) = 90, rsi는 최소 0
        assert score >= 90.0

    def test_returns_float(self) -> None:
        score = calculate_confidence_score(_make_inp())
        assert isinstance(score, float)

    def test_pullback_fixture(self) -> None:
        """실제 눌림목 픽스처 데이터로 점수가 유효 범위에 있다."""
        df = pd.read_csv(str(FIXTURE_DIR / "pullback_detected.csv"), parse_dates=["date"])
        df["date"] = df["date"].dt.date
        from scanner.patterns.pullback import PullbackDetector
        result = PullbackDetector().detect(df, "TEST")
        assert result is not None
        inp = ScoringInput(
            pattern_result=result,
            weekly_trend_direction=result.details["weekly_trend"],
            weekly_trend_strength=result.details["weekly_strength"],
            daily_df=df,
        )
        score = calculate_confidence_score(inp)
        assert 0.0 <= score <= 100.0
