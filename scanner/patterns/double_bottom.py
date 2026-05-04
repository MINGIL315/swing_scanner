"""쌍바닥 (Double Bottom) 패턴 탐지기."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from scanner.config import (
    DOUBLE_BOTTOM_LOOKBACK_DAYS,
    DOUBLE_BOTTOM_LOW_TOLERANCE_PCT,
    DOUBLE_BOTTOM_MAX_LOWS,
    DOUBLE_BOTTOM_MIN_LOWS,
    DOUBLE_BOTTOM_NECKLINE_GAIN_PCT,
)
from scanner.indicators.macd import macd
from scanner.indicators.rsi import rsi
from scanner.patterns.base import EntrySignal, PatternDetector, PatternResult


class DoubleBottomDetector(PatternDetector):
    """쌍바닥 패턴 탐지기.

    CLAUDE.md §5.1 정의:
    - 최근 60일 내 ±3% 이내의 저점 2~3개
    - 목선 = 저점 사이 최고점, 저점 평균 대비 5%↑ 이상
    - 두 번째 저점 이후 종가 > 목선 (최근 5거래일 내)
    """

    name: str = "double_bottom"
    display_name: str = "쌍바닥"

    # find_peaks 파라미터
    _PEAK_DISTANCE: int = 5      # 저점 간 최소 거리 (봉)
    _PEAK_PROMINENCE_PCT: float = 0.03  # 저점 prominence 최소값 (종가 대비 %)
    _BREAKOUT_WINDOW: int = 5    # 돌파 확인 최근 거래일 수

    def detect(
        self,
        df: pd.DataFrame,
        ticker: str = "",
    ) -> PatternResult | None:
        """쌍바닥 패턴을 탐지한다.

        Args:
            df    : 일봉 OHLCV DataFrame (최신 행이 마지막).
            ticker: 종목 코드.

        Returns:
            탐지 성공 시 PatternResult, 실패 시 None.
        """
        if len(df) < DOUBLE_BOTTOM_LOOKBACK_DAYS + self._PEAK_DISTANCE:
            return None

        window = df.tail(DOUBLE_BOTTOM_LOOKBACK_DAYS).reset_index(drop=True)
        close = window["close"].values.astype(float)

        # ── 저점 탐지 ────────────────────────────────────────────
        # prominence: 미세 노이즈 필터링 (종가 중앙값 대비 %)
        median_close = float(np.median(close))
        min_prominence = median_close * self._PEAK_PROMINENCE_PCT
        trough_indices, _ = find_peaks(
            -close,
            distance=self._PEAK_DISTANCE,
            prominence=min_prominence,
        )
        if len(trough_indices) < DOUBLE_BOTTOM_MIN_LOWS:
            return None

        # 가장 최근 MAX_LOWS 개 저점만 검토
        trough_indices = trough_indices[-DOUBLE_BOTTOM_MAX_LOWS:]
        trough_prices = close[trough_indices]

        # ── 저점 가격 ±3% 이내 ───────────────────────────────────
        low_min, low_max = trough_prices.min(), trough_prices.max()
        if low_min == 0:
            return None
        if (low_max - low_min) / low_min > DOUBLE_BOTTOM_LOW_TOLERANCE_PCT * 2:
            return None

        avg_low = float(trough_prices.mean())
        first_trough_idx = int(trough_indices[0])
        last_trough_idx = int(trough_indices[-1])

        # ── 목선 = 두 저점 사이 최고점 ───────────────────────────
        if first_trough_idx >= last_trough_idx:
            return None
        between_high = window["high"].values[first_trough_idx:last_trough_idx + 1]
        neckline = float(between_high.max())

        if neckline < avg_low * (1 + DOUBLE_BOTTOM_NECKLINE_GAIN_PCT):
            return None

        # ── 목선 돌파 확인 (최근 5거래일) ───────────────────────
        # 두 번째 저점 이후 구간에서 최근 BREAKOUT_WINDOW 행 검사
        post_trough = window.iloc[last_trough_idx + 1:]
        if len(post_trough) == 0:
            return None
        recent = post_trough.tail(self._BREAKOUT_WINDOW)
        if not (recent["close"] > neckline).any():
            return None

        # ── 진입가 / 손절 / 목표가 ───────────────────────────────
        entry_price = float(neckline * 1.005)   # 목선 돌파 확인 후 0.5% 위
        stop_loss = float(avg_low * 0.97)       # 두 저점 평균 -3%
        pattern_height = neckline - avg_low
        target_price = float(neckline + pattern_height)  # 패턴 높이만큼 목표

        risk = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else 0.0

        # ── raw_score (패턴 명확도 0~100) ────────────────────────
        raw_score = self._calc_raw_score(
            trough_prices=trough_prices,
            avg_low=avg_low,
            neckline=neckline,
            recent_close=float(window["close"].iloc[-1]),
            volume=window["volume"].values,
            last_trough_idx=last_trough_idx,
        )

        detected_at: date
        if "date" in df.columns:
            detected_at = df["date"].iloc[-1]
            if hasattr(detected_at, "date"):
                detected_at = detected_at.date()
        else:
            detected_at = date.today()

        details: dict[str, Any] = {
            "trough_prices": trough_prices.tolist(),
            "avg_low": round(avg_low, 4),
            "neckline": round(neckline, 4),
            "trough_count": len(trough_indices),
            "last_trough_idx_in_window": last_trough_idx,
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

        1. RSI 반등 (60분봉 없으면 일봉 RSI < 50에서 상승)
        2. 거래량 양봉 (종가 > 시가 + 거래량 양봉)
        3. MACD 상향 (히스토그램 양전환)
        4. 직전 고점 돌파 (최근 20일 고점 돌파)
        """
        signals: dict[str, bool] = {}

        close = df["close"]
        open_ = df["open"] if "open" in df.columns else close

        # 1. RSI 반등
        rsi_src = intraday_df["close"] if intraday_df is not None else close
        rsi_vals = rsi(rsi_src, 14)
        if len(rsi_vals.dropna()) >= 2:
            prev_rsi = float(rsi_vals.dropna().iloc[-2])
            curr_rsi = float(rsi_vals.dropna().iloc[-1])
            signals["rsi_bounce"] = (prev_rsi < 50) and (curr_rsi > prev_rsi)
        else:
            signals["rsi_bounce"] = False

        # 2. 거래량 양봉
        last_close = float(close.iloc[-1])
        last_open = float(open_.iloc[-1])
        if "volume" in df.columns and len(df) > 5:
            avg_vol = float(df["volume"].tail(5).mean())
            last_vol = float(df["volume"].iloc[-1])
            signals["bullish_volume"] = (last_close > last_open) and (last_vol > avg_vol)
        else:
            signals["bullish_volume"] = last_close > last_open

        # 3. MACD 히스토그램 양전환
        if len(close) >= 35:
            _, _, hist = macd(close)
            hist_valid = hist.dropna()
            if len(hist_valid) >= 2:
                signals["macd_cross"] = (
                    float(hist_valid.iloc[-2]) < 0
                    and float(hist_valid.iloc[-1]) > 0
                )
            else:
                signals["macd_cross"] = False
        else:
            signals["macd_cross"] = False

        # 4. 직전 20일 고점 돌파
        if "high" in df.columns and len(df) >= 21:
            prev_high = float(df["high"].iloc[-21:-1].max())
            signals["prev_high_break"] = last_close > prev_high
        else:
            signals["prev_high_break"] = False

        strength = sum(25.0 for v in signals.values() if v)
        return EntrySignal(strength=strength, signals=signals)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────

    def _calc_raw_score(
        self,
        trough_prices: np.ndarray,
        avg_low: float,
        neckline: float,
        recent_close: float,
        volume: np.ndarray,
        last_trough_idx: int,
    ) -> float:
        """패턴 명확도 점수를 계산한다 (0~100).

        구성 요소:
        - 저점 균일성 (30): 편차가 작을수록 고점수
        - 목선 높이 (30): 저점 대비 목선 상승폭이 클수록 고점수
        - 돌파 강도 (20): 현재 종가 > 목선 초과폭
        - 돌파 거래량 (20): 돌파 이후 평균 거래량 비율
        """
        score = 0.0

        # 저점 균일성
        if avg_low > 0:
            spread_pct = (trough_prices.max() - trough_prices.min()) / avg_low
            uniformity = max(0.0, 1.0 - spread_pct / (DOUBLE_BOTTOM_LOW_TOLERANCE_PCT * 2))
            score += uniformity * 30

        # 목선 높이
        if avg_low > 0:
            neck_gain = (neckline - avg_low) / avg_low
            neck_score = min(1.0, neck_gain / 0.10)  # 10%면 만점
            score += neck_score * 30

        # 돌파 강도
        if neckline > 0 and recent_close > neckline:
            break_pct = (recent_close - neckline) / neckline
            break_score = min(1.0, break_pct / 0.03)  # 3%면 만점
            score += break_score * 20

        # 돌파 거래량 (돌파 이후 거래량 vs 이전 평균)
        if last_trough_idx < len(volume) - 1:
            pre_vol = volume[:last_trough_idx + 1]
            post_vol = volume[last_trough_idx + 1:]
            if len(pre_vol) > 0 and pre_vol.mean() > 0:
                vol_ratio = post_vol.mean() / pre_vol.mean()
                vol_score = min(1.0, (vol_ratio - 1.0) / 0.5)  # 1.5배면 만점
                score += max(0.0, vol_score) * 20

        return min(100.0, score)
