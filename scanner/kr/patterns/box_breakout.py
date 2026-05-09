"""박스권 돌파 (Box Breakout) 패턴 탐지기."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from scanner.config import (
    BOX_BREAKOUT_BREAK_PCT,
    BOX_BREAKOUT_MAX_DAYS,
    BOX_BREAKOUT_MIN_DAYS,
    BOX_BREAKOUT_RANGE_PCT,
    BOX_BREAKOUT_RECENT_DAYS,
    BOX_BREAKOUT_VOLUME_RATIO,
)
from scanner.kr.indicators.macd import macd
from scanner.kr.indicators.rsi import rsi
from scanner.kr.indicators.volume import volume_ratio
from scanner.kr.patterns.base import EntrySignal, PatternDetector, PatternResult
from scanner.kr.quote_align import align_to_tick

# 박스 형성 윈도우 후보 (명확성 순으로 시도)
_BOX_WINDOWS: list[int] = [30, 45, 60]


@dataclass
class _BoxInfo:
    """박스권 정보."""

    window_days: int
    box_top: float      # 박스 상단 (고점 평균 기반)
    box_bottom: float   # 박스 하단 (저점 평균 기반)
    range_pct: float    # (고점-저점)/평균가 비율
    breakout_idx: int   # 돌파 발생 행 인덱스 (전체 df 기준)


def _find_best_box(df: pd.DataFrame) -> _BoxInfo | None:
    """30/45/60일 윈도우 중 가장 명확한 박스를 찾는다.

    명확성 기준: range_pct 가 가장 작으면서 BOX_BREAKOUT_RANGE_PCT 이하인 것.

    box_top / box_bottom 은 **종가 기반** (close.max / close.min) 으로 산출 —
    단일 wick (high/low extreme) 이 박스를 부풀리는 outlier 영향을 제거한다.
    박스의 의미 = 매수/매도가 균형을 이룬 종가 거래대 = 지지/저항선.
    """
    n = len(df)
    best: _BoxInfo | None = None

    for window in _BOX_WINDOWS:
        if n < window + BOX_BREAKOUT_RECENT_DAYS + 1:
            continue

        # 박스 구간: 최근 RECENT_DAYS 를 제외한 window 일
        box_end   = n - BOX_BREAKOUT_RECENT_DAYS - 1
        box_start = box_end - window
        if box_start < 0:
            continue

        box_df    = df.iloc[box_start:box_end + 1]
        mean_price = float(box_df["close"].mean())
        if mean_price == 0:
            continue

        box_top    = float(box_df["close"].max())
        box_bottom = float(box_df["close"].min())
        range_pct  = (box_top - box_bottom) / mean_price

        if range_pct > BOX_BREAKOUT_RANGE_PCT:
            continue

        # 돌파 확인: 최근 RECENT_DAYS 일 내 종가 > box_top * (1 + BREAK_PCT)
        recent_df  = df.iloc[box_end + 1:]
        breakout_threshold = box_top * (1 + BOX_BREAKOUT_BREAK_PCT)
        breakout_mask = recent_df["close"] > breakout_threshold
        if not breakout_mask.any():
            continue

        breakout_idx = int(breakout_mask[breakout_mask].index[-1])

        box = _BoxInfo(
            window_days=window,
            box_top=box_top,
            box_bottom=box_bottom,
            range_pct=range_pct,
            breakout_idx=breakout_idx,
        )

        if best is None or range_pct < best.range_pct:
            best = box

    return best


class BoxBreakoutDetector(PatternDetector):
    """박스권 돌파 패턴 탐지기.

    CLAUDE.md §5.3 정의:
    - 30~60일 윈도우 내 종가 max/min 기반 range ≤ 15% 박스권 형성
    - 가장 명확한(range_pct 최소) 박스 채택
    - 최근 1~3일 종가 > 박스 상단(종가 max) × 1.01
    - 돌파일 거래량 비율 ≥ 1.5
    """

    name: str = "box_breakout"
    display_name: str = "박스권 돌파"

    def detect(
        self,
        df: pd.DataFrame,
        ticker: str = "",
    ) -> PatternResult | None:
        """박스권 돌파 패턴을 탐지한다.

        Args:
            df    : 일봉 OHLCV DataFrame (최신 행이 마지막).
            ticker: 종목 코드.

        Returns:
            탐지 성공 시 PatternResult, 실패 시 None.
        """
        min_rows = BOX_BREAKOUT_MAX_DAYS + BOX_BREAKOUT_RECENT_DAYS + 1
        if len(df) < min_rows:
            return None

        df_reset = df.reset_index(drop=True)
        box = _find_best_box(df_reset)
        if box is None:
            return None

        # ── 돌파일 거래량 확인 ────────────────────────────────────
        vol_ratio_series = volume_ratio(df_reset["volume"])
        cross_vol_ratio = float(vol_ratio_series.iloc[box.breakout_idx])
        if pd.isna(cross_vol_ratio) or cross_vol_ratio < BOX_BREAKOUT_VOLUME_RATIO:
            return None

        # ── 진입가 / 손절 / 목표가 ───────────────────────────────
        last_close  = float(df_reset["close"].iloc[-1])
        entry_price = last_close
        stop_loss   = box.box_bottom * 0.98          # 박스 하단 -2%
        box_height  = box.box_top - box.box_bottom
        target_price = box.box_top + box_height      # 박스 높이만큼 목표

        risk   = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else 0.0

        raw_score = self._calc_raw_score(
            range_pct=box.range_pct,
            vol_ratio_at_break=cross_vol_ratio,
            break_pct=(last_close - box.box_top) / box.box_top if box.box_top != 0 else 0.0,
            days_since_break=len(df_reset) - 1 - box.breakout_idx,
        )

        detected_at: date
        if "date" in df.columns:
            detected_at = df["date"].iloc[-1]
            if hasattr(detected_at, "date"):
                detected_at = detected_at.date()
        else:
            detected_at = date.today()

        details: dict[str, Any] = {
            "window_days": box.window_days,
            "box_top": round(box.box_top, 4),
            "box_bottom": round(box.box_bottom, 4),
            "range_pct": round(box.range_pct * 100, 4),
            "breakout_idx": box.breakout_idx,
            "vol_ratio_at_break": round(cross_vol_ratio, 4),
            # scorer.py 가 details["vol_ratio"] 키를 찾는다 — 거래량 점수 (20% 가중치)
            "vol_ratio": round(cross_vol_ratio, 4),
        }

        return PatternResult(
            pattern_name=self.name,
            ticker=ticker,
            detected_at=detected_at,
            entry_price=align_to_tick(entry_price),
            stop_loss=align_to_tick(stop_loss),
            target_price=align_to_tick(target_price),
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

        1. RSI 50 돌파 (4시간봉 RSI 가 50 을 상향 돌파)
        2. 거래량 양봉 (4시간봉 양봉 + 거래량 > 직전 5봉 평균)
        3. MACD 히스토그램 양전환 (일봉 — 4h 봉 데이터 부족)
        4. 돌파 후 되돌림 없음 (일봉 종가 > 일봉 박스 상단)
        """
        signals: dict[str, bool] = {}
        close = df["close"]
        open_ = df["open"] if "open" in df.columns else close

        # 1. RSI 50 돌파 (4시간봉)
        rsi_src = intraday_df["close"] if intraday_df is not None else close
        rsi_vals = rsi(rsi_src, 14).dropna()
        if len(rsi_vals) >= 2:
            signals["rsi_above_50"] = (
                float(rsi_vals.iloc[-2]) < 50 and float(rsi_vals.iloc[-1]) > 50
            )
        else:
            signals["rsi_above_50"] = False

        # 2. 거래량 양봉 (4시간봉)
        vol_src = intraday_df if intraday_df is not None else df
        if "volume" in vol_src.columns and len(vol_src) > 5:
            src_close = float(vol_src["close"].iloc[-1])
            src_open = float(vol_src["open"].iloc[-1]) if "open" in vol_src.columns else src_close
            avg_vol = float(vol_src["volume"].tail(5).mean())
            signals["bullish_volume"] = (
                src_close > src_open
                and float(vol_src["volume"].iloc[-1]) > avg_vol
            )
        else:
            signals["bullish_volume"] = float(close.iloc[-1]) > float(open_.iloc[-1])

        # 일봉 컨텍스트 (MACD·박스 상단)
        last_close = float(close.iloc[-1])

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

        # 4. 박스 상단 위 유지 (되돌림 없음)
        df_reset = df.reset_index(drop=True)
        box = _find_best_box(df_reset)
        if box is not None:
            signals["above_box_top"] = last_close > box.box_top
        else:
            signals["above_box_top"] = False

        strength = sum(25.0 for v in signals.values() if v)
        return EntrySignal(strength=strength, signals=signals)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────

    def _calc_raw_score(
        self,
        range_pct: float,
        vol_ratio_at_break: float,
        break_pct: float,
        days_since_break: int,
    ) -> float:
        """패턴 명확도 점수 (0~100).

        구성 요소:
        - 박스 밀도 (30): range_pct 가 작을수록 고점수
        - 돌파 거래량 (30): 비율이 높을수록
        - 돌파 강도 (20): 박스 상단 초과폭
        - 돌파 신선도 (20): 돌파가 최근일수록
        """
        score = 0.0

        # 박스 밀도
        density = max(0.0, 1.0 - range_pct / BOX_BREAKOUT_RANGE_PCT)
        score += density * 30

        # 돌파 거래량
        vol_score = min(1.0, (vol_ratio_at_break - 1.0) / 1.0)
        score += max(0.0, vol_score) * 30

        # 돌파 강도
        break_score = min(1.0, break_pct / 0.05)
        score += max(0.0, break_score) * 20

        # 돌파 신선도
        freshness = max(0.0, 1.0 - days_since_break / BOX_BREAKOUT_RECENT_DAYS)
        score += freshness * 20

        return min(100.0, score)
