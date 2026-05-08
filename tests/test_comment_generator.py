"""comment_generator 단위 테스트."""
from __future__ import annotations

import pytest

from scanner.kr.reports.comment_generator import generate_comment


def _row(
    pattern: str = "pullback",
    trend: str = "uptrend",
    entry: float | None = 100.0,
    stop: float | None = 95.0,
    target: float | None = 110.0,
    rr: float | None = 2.0,
) -> dict:
    return {
        "pattern_name":      pattern,
        "trend_weekly":      trend,
        "entry_price":       entry,
        "stop_loss":         stop,
        "target_price":      target,
        "risk_reward_ratio": rr,
    }


class TestGenerateComment:
    def test_returns_four_phases(self) -> None:
        phases = generate_comment(_row())
        assert len(phases) == 4

    def test_phase_keys(self) -> None:
        for phase in generate_comment(_row()):
            assert "label" in phase
            assert "text" in phase
            assert isinstance(phase["label"], str)
            assert isinstance(phase["text"], str)

    def test_labels_are_correct(self) -> None:
        phases = generate_comment(_row())
        labels = [p["label"] for p in phases]
        assert labels == ["큰 추세", "패턴 분석", "진입 추천", "리스크 경고"]

    @pytest.mark.parametrize("trend", ["uptrend", "sideways", "downtrend"])
    def test_all_trends_produce_non_empty_text(self, trend: str) -> None:
        phases = generate_comment(_row(trend=trend))
        for phase in phases:
            assert len(phase["text"]) > 0

    @pytest.mark.parametrize("pattern", ["double_bottom", "golden_cross", "box_breakout", "pullback"])
    def test_all_patterns_produce_non_empty_text(self, pattern: str) -> None:
        phases = generate_comment(_row(pattern=pattern))
        pattern_phase = phases[1]
        assert len(pattern_phase["text"]) > 0

    def test_entry_prices_appear_in_entry_phase(self) -> None:
        phases = generate_comment(_row(entry=100.0, stop=95.0, target=110.0, rr=2.0))
        entry_text = phases[2]["text"]
        assert "100.00" in entry_text
        assert "95.00" in entry_text
        assert "110.00" in entry_text

    def test_missing_prices_uses_fallback(self) -> None:
        phases = generate_comment(_row(entry=None, stop=None, target=None, rr=None))
        entry_text = phases[2]["text"]
        assert "진입" in entry_text
        assert "100.00" not in entry_text

    def test_unknown_trend_uses_sideways_fallback(self) -> None:
        phases = generate_comment(_row(trend="unknown_value"))
        assert len(phases[0]["text"]) > 0
        assert len(phases[3]["text"]) > 0

    def test_unknown_pattern_uses_generic_text(self) -> None:
        phases = generate_comment(_row(pattern="mystery_pattern"))
        assert len(phases[1]["text"]) > 0

    def test_none_trend_uses_sideways_fallback(self) -> None:
        row = _row()
        row["trend_weekly"] = None
        phases = generate_comment(row)
        assert len(phases[0]["text"]) > 0

    def test_risk_reward_appears_in_entry_phase(self) -> None:
        phases = generate_comment(_row(entry=100.0, stop=95.0, target=110.0, rr=2.0))
        entry_text = phases[2]["text"]
        assert "1:2.0" in entry_text or "R:R" in entry_text

    def test_risk_percentage_in_entry_phase(self) -> None:
        # entry=100, stop=95 → risk 5%
        phases = generate_comment(_row(entry=100.0, stop=95.0, target=110.0, rr=2.0))
        entry_text = phases[2]["text"]
        assert "5.0%" in entry_text
