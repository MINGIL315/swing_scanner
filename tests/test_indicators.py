"""기술 지표 + 주봉 추세 판정 단위 테스트.

모든 테스트는 네트워크 없이 실행 가능하다.
실제 fetch 없이 합성(fixture) 데이터를 사용한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_df() -> pd.DataFrame:
    """tests/fixtures/sample_ohlcv.csv 를 로드한다."""
    path = FIXTURE_DIR / "sample_ohlcv.csv"
    df = pd.read_csv(str(path), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


def _make_df(close_values: list[float]) -> pd.DataFrame:
    """close 배열로 최소 OHLCV DataFrame을 만든다."""
    n = len(close_values)
    close = pd.array(close_values, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1_000_000.0] * n,
        }
    )


def _make_weekly_df(close_values: list[float]) -> pd.DataFrame:
    """주봉 형태의 최소 DataFrame을 만든다."""
    from datetime import date, timedelta

    df = _make_df(close_values)
    start = date(2020, 1, 6)
    df["week_start_date"] = [start + timedelta(weeks=i) for i in range(len(close_values))]
    return df


# ---------------------------------------------------------------------------
# SMA 테스트
# ---------------------------------------------------------------------------


class TestSma:
    def test_basic_value(self) -> None:
        """SMA(3) 마지막 값이 수작업 계산과 일치한다."""
        from scanner.us.indicators.moving_average import sma

        series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        result = sma(series, 3)
        # 마지막 3개 = 30, 40, 50 → 평균 40
        assert result.iloc[-1] == pytest.approx(40.0)

    def test_insufficient_data_is_nan(self) -> None:
        """데이터가 period 미만이면 NaN."""
        from scanner.us.indicators.moving_average import sma

        series = pd.Series([10.0, 20.0])
        result = sma(series, 5)
        assert result.isna().all()

    def test_length_preserved(self, sample_df: pd.DataFrame) -> None:
        """반환 시리즈 길이 = 입력 길이."""
        from scanner.us.indicators.moving_average import sma

        result = sma(sample_df["close"], 20)
        assert len(result) == len(sample_df)


# ---------------------------------------------------------------------------
# EMA 테스트
# ---------------------------------------------------------------------------


class TestEma:
    def test_ema_not_equal_sma(self) -> None:
        """EMA는 SMA와 다르다 (최근 값에 더 민감)."""
        from scanner.us.indicators.moving_average import ema, sma

        series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        assert ema(series, 3).iloc[-1] != sma(series, 3).iloc[-1]

    def test_ema_more_recent_weighted(self) -> None:
        """EMA는 최근 급등 후 SMA보다 높은 값을 가진다."""
        from scanner.us.indicators.moving_average import ema, sma

        series = pd.Series([10.0] * 20 + [100.0])
        assert ema(series, 5).iloc[-1] > sma(series, 5).iloc[-1]


# ---------------------------------------------------------------------------
# 정배열 / 역배열 테스트
# ---------------------------------------------------------------------------


class TestAlignment:
    def _row_with(self, ma5: float, ma20: float, ma60: float, ma120: float | None = None) -> pd.Series:
        d = {"close": 100.0, "ma_5": ma5, "ma_20": ma20, "ma_60": ma60}
        if ma120 is not None:
            d["ma_120"] = ma120
        return pd.Series(d)

    def test_bullish_alignment_true(self) -> None:
        from scanner.us.indicators.moving_average import is_bullish_alignment

        row = self._row_with(60, 50, 40, 30)
        assert is_bullish_alignment(row) is True

    def test_bullish_alignment_false_when_reversed(self) -> None:
        from scanner.us.indicators.moving_average import is_bullish_alignment

        row = self._row_with(40, 50, 60)
        assert is_bullish_alignment(row) is False

    def test_bullish_alignment_false_when_nan(self) -> None:
        from scanner.us.indicators.moving_average import is_bullish_alignment

        row = pd.Series({"ma_5": float("nan"), "ma_20": 50.0, "ma_60": 40.0})
        assert is_bullish_alignment(row) is False

    def test_bearish_alignment_true(self) -> None:
        from scanner.us.indicators.moving_average import is_bearish_alignment

        row = self._row_with(40, 50, 60)
        assert is_bearish_alignment(row) is True

    def test_bearish_alignment_false_when_bullish(self) -> None:
        from scanner.us.indicators.moving_average import is_bearish_alignment

        row = self._row_with(60, 50, 40)
        assert is_bearish_alignment(row) is False

    def test_bullish_excludes_ma120_violation(self) -> None:
        """ma_60 <= ma_120 이면 정배열 아님."""
        from scanner.us.indicators.moving_average import is_bullish_alignment

        row = self._row_with(60, 50, 40, ma120=45)  # ma60(40) < ma120(45) → False
        assert is_bullish_alignment(row) is False


# ---------------------------------------------------------------------------
# RSI 테스트
# ---------------------------------------------------------------------------


class TestRsi:
    def test_rsi_range(self, sample_df: pd.DataFrame) -> None:
        """RSI 값은 0~100 범위다."""
        from scanner.us.indicators.rsi import rsi

        result = rsi(sample_df["close"], 14)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_all_up_days_near_100(self) -> None:
        """계속 상승하는 데이터는 RSI 가 100에 가깝다."""
        from scanner.us.indicators.rsi import rsi

        series = pd.Series([float(i) for i in range(1, 51)])
        result = rsi(series, 14)
        assert result.iloc[-1] > 95.0

    def test_rsi_all_down_days_near_0(self) -> None:
        """계속 하락하는 데이터는 RSI 가 0에 가깝다."""
        from scanner.us.indicators.rsi import rsi

        series = pd.Series([float(50 - i) for i in range(50)])
        result = rsi(series, 14)
        assert result.iloc[-1] < 5.0

    def test_is_oversold(self) -> None:
        from scanner.us.indicators.rsi import is_oversold

        assert is_oversold(25.0) is True
        assert is_oversold(35.0) is False

    def test_is_overbought(self) -> None:
        from scanner.us.indicators.rsi import is_overbought

        assert is_overbought(75.0) is True
        assert is_overbought(65.0) is False

    def test_rsi_wilder_known_value(self) -> None:
        """알려진 단순 예시로 Wilder RSI 근사치 검증.

        14일 모두 상승(+1) → avg_gain=1, avg_loss=0 → RS=inf → RSI≈100.
        """
        from scanner.us.indicators.rsi import rsi

        series = pd.Series([float(i) for i in range(30)])
        result = rsi(series, 14)
        assert result.iloc[-1] == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# MACD 테스트
# ---------------------------------------------------------------------------


class TestMacd:
    def test_macd_returns_three_series(self, sample_df: pd.DataFrame) -> None:
        from scanner.us.indicators.macd import macd

        m, s, h = macd(sample_df["close"])
        assert len(m) == len(sample_df)
        assert len(s) == len(sample_df)
        assert len(h) == len(sample_df)

    def test_histogram_equals_macd_minus_signal(self, sample_df: pd.DataFrame) -> None:
        """histogram = macd_line − signal_line."""
        from scanner.us.indicators.macd import macd

        m, s, h = macd(sample_df["close"])
        diff = (m - s - h).dropna().abs()
        assert (diff < 1e-8).all()

    def test_bullish_cross_detected(self) -> None:
        """MACD 가 signal 을 상향 돌파하는 구간에서 True 반환."""
        from scanner.us.indicators.macd import is_bullish_cross

        # macd가 signal 아래 → 위로 올라오는 시나리오
        macd_s = pd.Series([-2.0, -1.0, -0.5, 0.5, 1.0])
        signal_s = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        assert is_bullish_cross(macd_s, signal_s, lookback=5) is True

    def test_bullish_cross_not_detected_when_already_above(self) -> None:
        """이미 macd > signal 상태가 지속되면 False."""
        from scanner.us.indicators.macd import is_bullish_cross

        macd_s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        signal_s = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        assert is_bullish_cross(macd_s, signal_s, lookback=5) is False

    def test_bullish_cross_outside_lookback_ignored(self) -> None:
        """lookback 범위 밖의 크로스는 탐지하지 않는다."""
        from scanner.us.indicators.macd import is_bullish_cross

        # 크로스는 index 1→2 (5개 중 앞쪽), lookback=2 이면 탐지 안 됨
        macd_s = pd.Series([-1.0, -0.5, 1.0, 1.5, 2.0])
        signal_s = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        assert is_bullish_cross(macd_s, signal_s, lookback=2) is False


# ---------------------------------------------------------------------------
# 거래량 테스트
# ---------------------------------------------------------------------------


class TestVolume:
    def test_volume_ratio_value(self) -> None:
        """현재 봉이 직전 20일 평균의 2배인 경우 ratio=2.0.

        shift(1) 설계: 현재 봉을 평균에서 제외하므로
        [100]*20 + [200] 에서 shift 후 rolling 평균은 정확히 100.0.
        """
        from scanner.us.indicators.volume import volume_ratio

        vol = pd.Series([100.0] * 20 + [200.0])
        result = volume_ratio(vol, period=20)
        assert result.iloc[-1] == pytest.approx(2.0, rel=0.01)

    def test_value_ratio_same_as_volume_ratio_logic(self) -> None:
        """value_ratio 는 volume_ratio 와 동일한 로직."""
        from scanner.us.indicators.volume import value_ratio

        val = pd.Series([1e9] * 20 + [3e9])
        result = value_ratio(val, period=20)
        assert result.iloc[-1] == pytest.approx(3.0, rel=0.01)

    def test_avg_value_rolling_mean(self) -> None:
        from scanner.us.indicators.volume import avg_value

        val = pd.Series([10.0] * 20)
        result = avg_value(val, period=20)
        assert result.iloc[-1] == pytest.approx(10.0)

    def test_is_volume_surge_true(self) -> None:
        from scanner.us.indicators.volume import is_volume_surge

        assert is_volume_surge(1.6, 1.5) is True

    def test_is_volume_surge_false(self) -> None:
        from scanner.us.indicators.volume import is_volume_surge

        assert is_volume_surge(1.4, 1.5) is False

    def test_is_volume_surge_nan(self) -> None:
        from scanner.us.indicators.volume import is_volume_surge

        assert is_volume_surge(float("nan")) is False


# ---------------------------------------------------------------------------
# enrich_dataframe 테스트
# ---------------------------------------------------------------------------


class TestEnrichDataframe:
    def test_daily_columns_added(self, sample_df: pd.DataFrame) -> None:
        from scanner.us.indicators import enrich_dataframe

        enriched = enrich_dataframe(sample_df, timeframe="daily")
        for col in ("ma_5", "ma_20", "ma_60", "ma_120", "rsi_14",
                    "macd_line", "macd_signal", "macd_hist", "volume_ratio_20"):
            assert col in enriched.columns, f"컬럼 누락: {col}"

    def test_weekly_no_macd(self, sample_df: pd.DataFrame) -> None:
        from scanner.us.indicators import enrich_dataframe

        enriched = enrich_dataframe(sample_df, timeframe="weekly")
        assert "macd_line" not in enriched.columns
        assert "ma_120" not in enriched.columns
        assert "rsi_14" in enriched.columns

    def test_value_columns_added_when_present(self, sample_df: pd.DataFrame) -> None:
        from scanner.us.indicators import enrich_dataframe

        enriched = enrich_dataframe(sample_df, timeframe="daily")
        assert "value_ratio_20" in enriched.columns
        assert "avg_value_20" in enriched.columns

    def test_original_df_not_modified(self, sample_df: pd.DataFrame) -> None:
        from scanner.us.indicators import enrich_dataframe

        original_cols = list(sample_df.columns)
        enrich_dataframe(sample_df, timeframe="daily")
        assert list(sample_df.columns) == original_cols


# ---------------------------------------------------------------------------
# WeeklyTrend 테스트
# ---------------------------------------------------------------------------


class TestWeeklyTrend:
    def _uptrend_df(self) -> pd.DataFrame:
        """완만하게 우상향하는 주봉 — uptrend 기대."""
        n = 80
        close = [100.0 + i * 0.3 + np.random.default_rng(1).normal(0, 0.5) for i in range(n)]
        return _make_weekly_df(close)

    def _downtrend_df(self) -> pd.DataFrame:
        """지속적으로 하락하는 주봉 — downtrend 기대."""
        n = 80
        # 주당 -1.5% 지수 감소 → MA60 기울기 ≤ -1.0% 임계값 충족
        close = [100.0 * (0.985 ** i) for i in range(n)]
        return _make_weekly_df(close)

    def _sideways_df(self) -> pd.DataFrame:
        """좁은 횡보 구간 주봉 — sideways 기대."""
        rng = np.random.default_rng(7)
        n = 80
        # MA20, MA60 이 교차할 정도의 진폭
        close = [50.0 + rng.uniform(-1.5, 1.5) for _ in range(n)]
        return _make_weekly_df(close)

    def test_uptrend_detected(self) -> None:
        from scanner.us.patterns.trend import detect_weekly_trend

        result = detect_weekly_trend(self._uptrend_df())
        assert result.direction == "uptrend", f"기대 uptrend, 실제 {result.direction}: {result.details}"

    def test_downtrend_detected(self) -> None:
        from scanner.us.patterns.trend import detect_weekly_trend

        result = detect_weekly_trend(self._downtrend_df())
        assert result.direction == "downtrend", f"기대 downtrend, 실제 {result.direction}: {result.details}"

    def test_sideways_detected(self) -> None:
        from scanner.us.patterns.trend import detect_weekly_trend

        result = detect_weekly_trend(self._sideways_df())
        assert result.direction == "sideways", f"기대 sideways, 실제 {result.direction}: {result.details}"

    def test_insufficient_data_returns_sideways(self) -> None:
        from scanner.us.patterns.trend import detect_weekly_trend

        df = _make_weekly_df([100.0] * 10)
        result = detect_weekly_trend(df)
        assert result.direction == "sideways"

    def test_strength_sign(self) -> None:
        """상승 추세 strength > 0, 하락 추세 strength < 0."""
        from scanner.us.patterns.trend import detect_weekly_trend

        up = detect_weekly_trend(self._uptrend_df())
        down = detect_weekly_trend(self._downtrend_df())
        assert up.strength > 0
        assert down.strength < 0

    def test_result_fields_populated(self) -> None:
        from scanner.us.patterns.trend import detect_weekly_trend

        result = detect_weekly_trend(self._uptrend_df())
        assert isinstance(result.ma20_above_ma60, bool)
        assert isinstance(result.price_above_ma20, bool)
        assert isinstance(result.ma60_slope, float)
        assert "close" in result.details
