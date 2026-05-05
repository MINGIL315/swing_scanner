"""눌림목 (Pullback in Uptrend) 패턴 탐지기."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from scanner.config import (
    MA_LONG,
    MA_MEDIUM,
    MA_SHORT,
    PULLBACK_MA_NEAR_PCT,
    PULLBACK_VOLUME_LOOKBACK,
)
from scanner.indicators.macd import macd
from scanner.indicators.moving_average import sma
from scanner.indicators.rsi import rsi
from scanner.patterns.base import EntrySignal, PatternDetector, PatternResult
from scanner.patterns.trend import detect_weekly_trend

# 주봉 추세 판정에 필요한 최소 일봉 행 수 (64주 × 5일 + 여유)
_MIN_DAILY_ROWS: int = 350
# 20일 고점 상승 여력 확인 임계값
_HIGH_GAP_MIN_PCT: float = 0.05


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame을 주봉으로 리샘플링한다.

    date 컬럼(혹은 인덱스)을 기준으로 월요일 시작 주 단위로 집계한다.

    마지막 주가 _미완성_ (일봉 데이터가 아직 그 주 금요일까지 닿지 않음)이면
    부분 캔들이 추세 판정·차트 표시에 섞이지 않도록 drop 한다.
    이는 TradingView 의 ``Once Per Bar Close`` 알람과 동일한 의미로, 스크리너·
    백테스트 모두에서 신호 안정성을 보장한다.
    """
    df_w = df.copy()
    if "date" in df_w.columns:
        df_w["date"] = pd.to_datetime(df_w["date"])
        df_w = df_w.set_index("date")
    df_w.index = pd.to_datetime(df_w.index)

    if df_w.empty:
        return pd.DataFrame(
            columns=["week_start_date", "open", "high", "low", "close", "volume"]
        )

    last_daily = df_w.index.max()

    weekly = df_w.resample("W-MON", label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    weekly = weekly.dropna(subset=["close"])
    weekly = weekly.reset_index().rename(columns={"date": "week_start_date"})

    # 마지막 주가 미완성이면 drop. 완성 기준: 일봉 마지막 날짜가 그 주 금요일(월+4) 이상.
    if not weekly.empty:
        last_week_start = pd.Timestamp(weekly.iloc[-1]["week_start_date"])
        expected_week_end = last_week_start + pd.Timedelta(days=4)  # Friday
        if last_daily < expected_week_end:
            weekly = weekly.iloc[:-1].reset_index(drop=True)

    return weekly


class PullbackDetector(PatternDetector):
    """눌림목 패턴 탐지기.

    CLAUDE.md §5.4 정의:
    - 주봉 추세 = 상승 (필수 조건)
    - 일봉 정배열: MA5 > MA20 > MA60
    - 현재가가 MA20 또는 MA60의 ±2% 범위 안에 위치
    - 당일 캔들이 양봉 (close > open)
    - 거래량이 최근 5일 평균보다 큼
    """

    name: str = "pullback"
    display_name: str = "눌림목"

    def detect(
        self,
        df: pd.DataFrame,
        ticker: str = "",
    ) -> PatternResult | None:
        """눌림목 패턴을 탐지한다.

        Args:
            df    : 일봉 OHLCV DataFrame (최신 행이 마지막).
            ticker: 종목 코드.

        Returns:
            탐지 성공 시 PatternResult, 실패 시 None.
        """
        if len(df) < _MIN_DAILY_ROWS:
            return None

        # ── 주봉 추세 확인 ────────────────────────────────────────
        weekly_df = _resample_weekly(df)
        trend = detect_weekly_trend(weekly_df)
        if trend.direction != "uptrend":
            return None

        # ── 일봉 이동평균 계산 ────────────────────────────────────
        df_r = df.reset_index(drop=True)
        close = df_r["close"]
        ma5 = sma(close, MA_SHORT)
        ma20 = sma(close, MA_MEDIUM)
        ma60 = sma(close, MA_LONG)

        last_ma5 = float(ma5.iloc[-1])
        last_ma20 = float(ma20.iloc[-1])
        last_ma60 = float(ma60.iloc[-1])
        last_close = float(close.iloc[-1])

        if any(pd.isna(v) for v in (last_ma5, last_ma20, last_ma60)):
            return None

        # ── 정배열 확인 ───────────────────────────────────────────
        if not (last_ma5 > last_ma20 > last_ma60):
            return None

        # ── MA20 또는 MA60 근접 확인 (±2%) ───────────────────────
        near_ma20 = abs(last_close - last_ma20) / last_ma20 <= PULLBACK_MA_NEAR_PCT
        near_ma60 = abs(last_close - last_ma60) / last_ma60 <= PULLBACK_MA_NEAR_PCT
        if not (near_ma20 or near_ma60):
            return None

        # ── 당일 양봉 확인 ────────────────────────────────────────
        if "open" not in df_r.columns:
            return None
        last_open = float(df_r["open"].iloc[-1])
        if last_close <= last_open:
            return None

        # ── 거래량 확인 ───────────────────────────────────────────
        if "volume" not in df_r.columns or len(df_r) <= PULLBACK_VOLUME_LOOKBACK:
            return None
        last_vol = float(df_r["volume"].iloc[-1])
        avg_vol = float(
            df_r["volume"].iloc[-(PULLBACK_VOLUME_LOOKBACK + 1):-1].mean()
        )
        if avg_vol == 0 or last_vol <= avg_vol:
            return None

        # ── 진입가 / 손절 / 목표가 ───────────────────────────────
        entry_price = last_close
        stop_loss = last_ma60 * 0.97        # MA60 -3%
        # 20일 고점 기준 목표
        if "high" in df_r.columns and len(df_r) >= 21:
            target_price = float(df_r["high"].iloc[-21:-1].max())
            if target_price <= entry_price:
                target_price = entry_price * 1.08
        else:
            target_price = entry_price * 1.08

        risk = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else 0.0

        raw_score = self._calc_raw_score(
            weekly_strength=trend.strength,
            ma_gap_5_20=(last_ma5 - last_ma20) / last_ma20 if last_ma20 != 0 else 0.0,
            proximity_pct=min(
                abs(last_close - last_ma20) / last_ma20,
                abs(last_close - last_ma60) / last_ma60,
            ),
            vol_ratio=last_vol / avg_vol if avg_vol != 0 else 0.0,
        )

        detected_at: date
        if "date" in df.columns:
            detected_at = df["date"].iloc[-1]
            if hasattr(detected_at, "date"):
                detected_at = detected_at.date()
        else:
            detected_at = date.today()

        details: dict[str, Any] = {
            "weekly_trend": trend.direction,
            "weekly_strength": round(trend.strength, 4),
            "ma5": round(last_ma5, 4),
            "ma20": round(last_ma20, 4),
            "ma60": round(last_ma60, 4),
            "near_ma20": near_ma20,
            "near_ma60": near_ma60,
            "vol_ratio": round(last_vol / avg_vol, 4) if avg_vol != 0 else 0.0,
        }

        return PatternResult(
            pattern_name=self.name,
            ticker=ticker,
            detected_at=detected_at,
            entry_price=round(entry_price, 4),
            stop_loss=round(stop_loss, 4),
            target_price=round(target_price, 4),
            risk_reward_ratio=rr,
            raw_score=round(raw_score, 2),
            details=details,
        )

    def entry_signal(
        self,
        df: pd.DataFrame,
        intraday_df: pd.DataFrame | None = None,
    ) -> EntrySignal:
        """진입 신호 4가지를 평가한다 (각 25점).

        1. RSI 반등 (40~70, 상향)
        2. 거래량 양봉
        3. MACD 히스토그램 양전환
        4. MA20 위로 회복 (종가 > MA20)
        """
        signals: dict[str, bool] = {}
        close = df["close"]
        open_ = df["open"] if "open" in df.columns else close

        # 1. RSI 반등
        rsi_src = intraday_df["close"] if intraday_df is not None else close
        rsi_vals = rsi(rsi_src, 14).dropna()
        if len(rsi_vals) >= 2:
            prev_r = float(rsi_vals.iloc[-2])
            curr_r = float(rsi_vals.iloc[-1])
            signals["rsi_bounce"] = (40 < curr_r < 70) and curr_r > prev_r
        else:
            signals["rsi_bounce"] = False

        # 2. 거래량 양봉
        last_close = float(close.iloc[-1])
        last_open = float(open_.iloc[-1])
        if "volume" in df.columns and len(df) > 5:
            avg_vol = float(df["volume"].tail(5).mean())
            signals["bullish_volume"] = (
                last_close > last_open
                and float(df["volume"].iloc[-1]) > avg_vol
            )
        else:
            signals["bullish_volume"] = last_close > last_open

        # 3. MACD 히스토그램 양전환
        if len(close) >= 35:
            _, _, hist = macd(close)
            hist_valid = hist.dropna()
            if len(hist_valid) >= 2:
                signals["macd_positive"] = (
                    float(hist_valid.iloc[-2]) < 0
                    and float(hist_valid.iloc[-1]) > 0
                )
            else:
                signals["macd_positive"] = False
        else:
            signals["macd_positive"] = False

        # 4. MA20 위 회복
        if len(close) >= MA_MEDIUM:
            ma20_val = float(sma(close, MA_MEDIUM).iloc[-1])
            signals["above_ma20"] = not pd.isna(ma20_val) and last_close > ma20_val
        else:
            signals["above_ma20"] = False

        strength = sum(25.0 for v in signals.values() if v)
        return EntrySignal(strength=strength, signals=signals)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────

    def _calc_raw_score(
        self,
        weekly_strength: float,
        ma_gap_5_20: float,
        proximity_pct: float,
        vol_ratio: float,
    ) -> float:
        """패턴 명확도 점수 (0~100).

        구성 요소:
        - 주봉 강도 (30): 주봉 추세 강도 (MA20 대비 이격률)
        - MA 정배열 간격 (25): MA5-MA20 갭이 적당히 벌어질수록
        - MA 근접도 (25): 현재가가 MA에 가까울수록 고점수
        - 거래량 (20): 평균 대비 거래량 비율
        """
        score = 0.0

        # 주봉 강도 (0~5% 이격이 최대)
        w_score = min(1.0, max(0.0, weekly_strength / 5.0))
        score += w_score * 30

        # MA 정배열 간격 (0~2% 갭이 자연스러운 정배열)
        gap_score = min(1.0, ma_gap_5_20 / 0.02)
        score += max(0.0, gap_score) * 25

        # MA 근접도 (가까울수록 고점수)
        prox_score = max(0.0, 1.0 - proximity_pct / PULLBACK_MA_NEAR_PCT)
        score += prox_score * 25

        # 거래량
        vol_score = min(1.0, (vol_ratio - 1.0) / 0.5)
        score += max(0.0, vol_score) * 20

        return min(100.0, score)
