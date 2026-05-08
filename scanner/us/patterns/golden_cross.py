"""골든크로스 (Golden Cross) 패턴 탐지기."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from scanner.config import (
    GOLDEN_CROSS_FAST_MA,
    GOLDEN_CROSS_RECENT_DAYS,
    GOLDEN_CROSS_SLOW_MA,
    GOLDEN_CROSS_VOLUME_RATIO,
)
from scanner.us.indicators.macd import macd
from scanner.us.indicators.moving_average import sma
from scanner.us.indicators.rsi import rsi
from scanner.us.indicators.volume import volume_ratio
from scanner.us.patterns.base import EntrySignal, PatternDetector, PatternResult

# MA60 기울기 판정 기간/임계값
_SLOPE_WINDOW: int = 20
_SLOPE_MIN_PCT: float = -0.005   # ≥ -0.5% 면 평탄 or 상승


class GoldenCrossDetector(PatternDetector):
    """골든크로스 패턴 탐지기.

    CLAUDE.md §5.2 정의:
    - 20일 이동평균선이 60일선을 5일 이내에 상향 돌파
    - 60일선이 평탄(횡보) 또는 상승 상태
    - 돌파 시점 거래량 ≥ 최근 20일 평균의 1.2배
    """

    name: str = "golden_cross"
    display_name: str = "골든크로스"

    def detect(
        self,
        df: pd.DataFrame,
        ticker: str = "",
    ) -> PatternResult | None:
        """골든크로스 패턴을 탐지한다.

        Args:
            df    : 일봉 OHLCV DataFrame (최신 행이 마지막).
            ticker: 종목 코드.

        Returns:
            탐지 성공 시 PatternResult, 실패 시 None.
        """
        min_rows = GOLDEN_CROSS_SLOW_MA + GOLDEN_CROSS_RECENT_DAYS + _SLOPE_WINDOW
        if len(df) < min_rows:
            return None

        close = df["close"].reset_index(drop=True)
        ma_fast = sma(close, GOLDEN_CROSS_FAST_MA)
        ma_slow = sma(close, GOLDEN_CROSS_SLOW_MA)
        vol_ratio = volume_ratio(df["volume"].reset_index(drop=True))

        # ── 최근 N일 내 골든크로스 탐지 ────────────────────────
        cross_idx: int | None = None
        window = GOLDEN_CROSS_RECENT_DAYS + 1  # 크로스 확인을 위해 +1

        for i in range(len(close) - window, len(close) - 1):
            if i < 1:
                continue
            prev_fast = ma_fast.iloc[i - 1]
            prev_slow = ma_slow.iloc[i - 1]
            curr_fast = ma_fast.iloc[i]
            curr_slow = ma_slow.iloc[i]

            if any(pd.isna(v) for v in (prev_fast, prev_slow, curr_fast, curr_slow)):
                continue

            if float(prev_fast) <= float(prev_slow) and float(curr_fast) > float(curr_slow):
                cross_idx = i
                break

        if cross_idx is None:
            return None

        # ── MA60 기울기 확인 (평탄 or 상승) ─────────────────────
        ma60_window = ma_slow.dropna().iloc[-_SLOPE_WINDOW:]
        if len(ma60_window) < 2:
            return None
        first_val = float(ma60_window.iloc[0])
        last_val = float(ma60_window.iloc[-1])
        slope_pct = (last_val - first_val) / first_val if first_val != 0 else 0.0

        if slope_pct < _SLOPE_MIN_PCT:
            return None

        # ── 돌파일 거래량 확인 ────────────────────────────────────
        cross_vol_ratio = float(vol_ratio.iloc[cross_idx])
        if pd.isna(cross_vol_ratio) or cross_vol_ratio < GOLDEN_CROSS_VOLUME_RATIO:
            return None

        # ── 진입가 / 손절 / 목표가 ───────────────────────────────
        last_close = float(close.iloc[-1])
        last_ma20  = float(ma_fast.iloc[-1])
        last_ma60  = float(ma_slow.iloc[-1])

        entry_price = last_close
        stop_loss   = last_ma60 * 0.97          # MA60 -3%
        target_price = last_close * 1.10        # +10% 목표

        risk   = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else 0.0

        raw_score = self._calc_raw_score(
            slope_pct=slope_pct,
            vol_ratio_at_cross=cross_vol_ratio,
            ma_gap_pct=(last_ma20 - last_ma60) / last_ma60 if last_ma60 != 0 else 0.0,
            days_since_cross=len(close) - 1 - cross_idx,
        )

        detected_at: date
        if "date" in df.columns:
            detected_at = df["date"].iloc[-1]
            if hasattr(detected_at, "date"):
                detected_at = detected_at.date()
        else:
            detected_at = date.today()

        details: dict[str, Any] = {
            "cross_idx": cross_idx,
            "days_since_cross": len(close) - 1 - cross_idx,
            "ma60_slope_pct": round(slope_pct * 100, 4),
            "vol_ratio_at_cross": round(cross_vol_ratio, 4),
            "last_ma20": round(last_ma20, 4),
            "last_ma60": round(last_ma60, 4),
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

        1. RSI 상승 (30~70 구간, 상향)
        2. 거래량 양봉
        3. MACD 히스토그램 양전환
        4. 종가 > MA20
        """
        signals: dict[str, bool] = {}
        close = df["close"]
        open_ = df["open"] if "open" in df.columns else close

        # 1. RSI 상승
        rsi_src = intraday_df["close"] if intraday_df is not None else close
        rsi_vals = rsi(rsi_src, 14).dropna()
        if len(rsi_vals) >= 2:
            prev_r = float(rsi_vals.iloc[-2])
            curr_r = float(rsi_vals.iloc[-1])
            signals["rsi_rising"] = (30 < curr_r < 70) and curr_r > prev_r
        else:
            signals["rsi_rising"] = False

        # 2. 거래량 양봉
        last_close = float(close.iloc[-1])
        last_open  = float(open_.iloc[-1])
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

        # 4. 종가 > MA20
        if len(close) >= GOLDEN_CROSS_FAST_MA:
            ma20_val = float(sma(close, GOLDEN_CROSS_FAST_MA).iloc[-1])
            signals["above_ma20"] = not pd.isna(ma20_val) and last_close > ma20_val
        else:
            signals["above_ma20"] = False

        strength = sum(25.0 for v in signals.values() if v)
        return EntrySignal(strength=strength, signals=signals)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────

    def _calc_raw_score(
        self,
        slope_pct: float,
        vol_ratio_at_cross: float,
        ma_gap_pct: float,
        days_since_cross: int,
    ) -> float:
        """패턴 명확도 점수 (0~100).

        구성 요소:
        - MA60 기울기 (30): 상승할수록 고점수
        - 돌파 거래량 (30): 비율이 높을수록 고점수
        - MA 이격 (20): 교차 직후 갭이 적당히 벌어질수록
        - 교차 신선도 (20): 교차가 최근일수록
        """
        score = 0.0

        # MA60 기울기
        slope_score = min(1.0, max(0.0, (slope_pct - _SLOPE_MIN_PCT) / 0.02))
        score += slope_score * 30

        # 돌파 거래량
        vol_score = min(1.0, (vol_ratio_at_cross - 1.0) / 1.0)
        score += max(0.0, vol_score) * 30

        # MA 이격 (0~3% 사이 적정)
        gap_score = min(1.0, ma_gap_pct / 0.03)
        score += max(0.0, gap_score) * 20

        # 교차 신선도 (0일=100%, 5일=0%)
        freshness = max(0.0, 1.0 - days_since_cross / GOLDEN_CROSS_RECENT_DAYS)
        score += freshness * 20

        return min(100.0, score)
