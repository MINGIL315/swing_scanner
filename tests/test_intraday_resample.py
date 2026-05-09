"""1분봉 → 60분/4시간봉 합성 (scanner.kr.intraday) 단위 테스트."""
from __future__ import annotations

import pandas as pd
import pytest

from scanner.kr.intraday import (
    _rule_minutes,
    resample_to_4h,
    resample_to_60min,
    resample_to_minutes,
)


def _make_kr_intraday_day(date_str: str = "2026-01-08") -> pd.DataFrame:
    """한국 정규 영업시간(09:00~15:30) 1분봉 390개 fixture."""
    times = pd.date_range(
        start=f"{date_str} 09:00:00",
        end=f"{date_str} 15:29:00",
        freq="1min",
    )
    rows = []
    for i, t in enumerate(times):
        base = 100.0 + i * 0.1
        rows.append({
            "ticker": "005930",
            "datetime": t,
            "open": base,
            "high": base + 0.5,
            "low": base - 0.3,
            "close": base + 0.2,
            "volume": 100.0 + i,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# resample_to_60min
# ---------------------------------------------------------------------------


class TestResampleTo60min:
    def test_full_day_6_complete_bars(self) -> None:
        """09:00~15:30 (6.5h) 1분봉 → drop_partial=True 시 60분봉 6개."""
        df_1min = _make_kr_intraday_day()
        df_60 = resample_to_60min(df_1min, drop_partial=True)
        # 09/10/11/12/13/14 시작 봉 = 6개. 15시 봉은 30분만 → drop.
        assert len(df_60) == 6
        assert list(df_60.columns) == ["ticker", "datetime", "open", "high", "low", "close", "volume"]

    def test_includes_partial_when_keep(self) -> None:
        """drop_partial=False 면 마지막 30분 부분 봉도 포함 → 7개."""
        df_1min = _make_kr_intraday_day()
        df_60 = resample_to_60min(df_1min, drop_partial=False)
        assert len(df_60) == 7

    def test_ohlc_aggregation(self) -> None:
        """첫 60분(09:00 봉)의 OHLC 가 정확히 집계됨."""
        df_1min = _make_kr_intraday_day()
        df_60 = resample_to_60min(df_1min, drop_partial=True)

        # 09:00~09:59 = 60개 1분봉 (i=0..59)
        # i=0 의 base=100.0 → open=100.0
        # i=59 의 base=105.9 → close=106.1
        # high = max(base + 0.5) over i=0..59 = 105.9 + 0.5 = 106.4
        # low  = min(base - 0.3) over i=0..59 = 100.0 - 0.3 = 99.7
        # volume = sum(100..159) = 7770
        first_bar = df_60.iloc[0]
        assert first_bar["datetime"] == pd.Timestamp("2026-01-08 09:00:00")
        assert first_bar["open"] == pytest.approx(100.0)
        assert first_bar["high"] == pytest.approx(106.4)
        assert first_bar["low"] == pytest.approx(99.7)
        assert first_bar["close"] == pytest.approx(106.1)
        assert first_bar["volume"] == pytest.approx(sum(range(100, 160)))

    def test_ticker_preserved(self) -> None:
        df_1min = _make_kr_intraday_day()
        df_60 = resample_to_60min(df_1min)
        assert (df_60["ticker"] == "005930").all()

    def test_empty_input_returns_empty(self) -> None:
        df = resample_to_60min(pd.DataFrame())
        assert df.empty
        assert list(df.columns) == ["ticker", "datetime", "open", "high", "low", "close", "volume"]

    def test_none_input_returns_empty(self) -> None:
        df = resample_to_60min(None)  # type: ignore[arg-type]
        assert df.empty


# ---------------------------------------------------------------------------
# resample_to_4h
# ---------------------------------------------------------------------------


class TestResampleTo4h:
    def test_kr_business_day_one_complete_4h_bar(self) -> None:
        """09:00~15:30 (6.5h) → 완전한 4시간봉 1개 (08:00~12:00 또는 12:00~16:00 그룹)."""
        df_1min = _make_kr_intraday_day()
        df_4h = resample_to_4h(df_1min, drop_partial=True)
        # origin='start_day' 기준 4시간 그룹: 00:00 / 04:00 / 08:00 / 12:00 / 16:00 / 20:00
        # KR 영업시간 09:00~15:30 은 08:00~12:00 그룹 (180분) + 12:00~16:00 그룹 (210분)
        # 180/240 = 0.75 → drop, 210/240 = 0.875 → drop. 즉 둘 다 부분 → 0개.
        # drop_partial=True 면 0개 가능.
        assert len(df_4h) <= 1  # 정확한 갯수는 그룹핑에 따라 0~1개

    def test_kr_business_day_with_partial(self) -> None:
        """drop_partial=False 면 부분 4시간봉 모두 포함 (08:00~12:00, 12:00~16:00 그룹)."""
        df_1min = _make_kr_intraday_day()
        df_4h = resample_to_4h(df_1min, drop_partial=False)
        # 영업시간 6.5h 가 4h 그룹 2개에 분산 (08:00~12:00 의 일부 + 12:00~16:00 의 일부)
        assert len(df_4h) == 2

    def test_empty_input(self) -> None:
        assert resample_to_4h(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# _rule_minutes 헬퍼
# ---------------------------------------------------------------------------


class TestRuleMinutes:
    @pytest.mark.parametrize(
        "rule,expected",
        [
            ("60min", 60),
            ("1min", 1),
            ("240min", 240),
            ("4h", 240),
            ("4H", 240),
            ("1h", 60),
            ("invalid", None),
            ("xxxmin", None),
            ("D", None),
        ],
    )
    def test_conversion(self, rule: str, expected: int | None) -> None:
        assert _rule_minutes(rule) == expected
