"""박스권 돌파 (Box Breakout) 패턴 탐지기 — v3.

v3 강화 (2026-05-10):
1. 가짜 멀티 윈도우 폐기. 메인 60일 + 단기 20일 응축의 진짜 분리 구조.
2. MA 기울기 비대칭 게이트 — 하락 추세 끝물 박스 거부, 재축적 박스 친화.
3. Pivot 기반 터치 카운트 — "시장 참여자 반복 의식" 검증.
4. ATR 변동성 압축 메트릭 (점수용).
5. ATR 가중 돌파 강도 + 캔들 품질 (점수용).
6. ``raw_score`` 7요소 구성 (밀도 / 단기응축 / 변동성응축 / 터치 / 거래량 / 강도 / 신선도).
7. ``vol_ratio`` 키 통일 (scorer 와 일치).

CLAUDE.md §5.3 박스권 돌파 정의를 v3 기준으로 보강한 형태.
시장 분리 정책에 따라 본 파일은 KR 전용. US 모듈은 동일 코드 복제.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from scipy.signal import find_peaks

from scanner.config import (
    BOX_BREAKOUT_BREAK_PCT,
    BOX_BREAKOUT_RANGE_PCT,
    BOX_BREAKOUT_RECENT_DAYS,
    BOX_BREAKOUT_VOLUME_RATIO,
)
from scanner.kr.indicators.atr import atr as atr_func
from scanner.kr.indicators.macd import macd
from scanner.kr.indicators.moving_average import sma
from scanner.kr.indicators.rsi import rsi
from scanner.kr.indicators.volume import volume_ratio
from scanner.kr.patterns.base import EntrySignal, PatternDetector, PatternResult
from scanner.kr.quote_align import align_to_tick

# ---------------------------------------------------------------------------
# v3 모듈 상수
# ---------------------------------------------------------------------------

# 윈도우 (v3 — 가짜 멀티 [30,45,60] 폐기)
_MAIN_WINDOW: int = 60                  # 메인 박스 (지지/저항 인식 구간)
_SHORT_WINDOW: int = 20                 # 단기 응축 검증 구간

# 단기 응축 게이트
_SHORT_COMPRESSION_MAX: float = 0.70    # short_range / main_range 상한

# 추세 둔화 (비대칭) — 재축적 박스 친화, 하락 끝물 박스 거부
# MA20 슬로프 윈도우 = 10거래일, MA60 슬로프 윈도우 = 20거래일
_MA20_SLOPE_WINDOW: int = 10
_MA60_SLOPE_WINDOW: int = 20
_MA20_SLOPE_MIN: float = -0.050         # 단기 MA 10일 누적 변화율 하한 (KOSPI 변동성 반영)
_MA20_SLOPE_MAX: float = 0.050          # 단기 MA 10일 누적 변화율 상한
_MA60_SLOPE_MIN: float = -0.020         # 장기 MA 20일 누적 변화율 하한 (장기 하락만 거부)

# Pivot 추출
_PIVOT_DISTANCE: int = 5                # 최소 pivot 간격 (거래일)
_PIVOT_PROMINENCE_ATR_MULT: float = 0.5 # ATR 0.5배 = pivot 인정 최소 폭 (KOSPI200 종목의 자연스런 변동 대비 적정선; 1.0배는 빡빡해 통과 종목 0건)

# Touch Count
_TOUCH_TOLERANCE_ATR_MULT: float = 1.5  # 동적 tolerance 가중치
_TOUCH_TOLERANCE_MIN: float = 0.015     # 1.5% (저변동 종목 안전장치)
_TOUCH_TOLERANCE_MAX: float = 0.035     # 3.5% (고변동 종목 안전장치)
_TOUCH_MIN_GAP_DAYS: int = 5            # 같은 가격대 터치 간 최소 거래일 (60일 박스에 슬롯 12개)
_TOUCH_MIN_TOP: int = 2
_TOUCH_MIN_BOTTOM: int = 2

# ATR 변동성 응축 (점수용)
_ATR_COMPRESSION_MAX: float = 0.85      # 점수 시작 (1.0 → 0점, 0.7 → 만점)

# 강한 박스 분류 (메타정보)
_STRONG_TOUCH_MIN: int = 3
_STRONG_COMPRESSION_MAX: float = 0.50

# detect 진입 최소 행 수
# = MA60 슬로프 산출에 box_end - (MA60_SLOPE_WINDOW - 1) >= 59 (SMA60 valid 시작)
# → box_end >= 59 + (MA60_SLOPE_WINDOW - 1) = 59 + 19 = 78
# → n >= 78 + RECENT_DAYS + 1 = 78 + 3 + 1 = 82
_MIN_ROWS: int = _MAIN_WINDOW + (_MA60_SLOPE_WINDOW - 1) + BOX_BREAKOUT_RECENT_DAYS + 1


# ---------------------------------------------------------------------------
# 박스 정보 dataclass (v3 확장)
# ---------------------------------------------------------------------------


@dataclass
class _BoxInfo:
    """박스권 탐지 결과 메트릭.

    Attributes:
        box_top           : 메인 60일 박스 상단 (종가 max).
        box_bottom        : 메인 60일 박스 하단 (종가 min).
        range_pct         : 메인 박스 폭 ((top-bottom)/mean).
        short_top         : 단기 20일 박스 상단.
        short_bottom      : 단기 20일 박스 하단.
        short_range_pct   : 단기 박스 폭.
        compression_ratio : short_range_pct / range_pct (응축 비율).
        breakout_idx      : 돌파 발생 행 인덱스 (전체 df 기준).
        top_touch         : 박스 상단 터치 카운트 (시간 분산 적용).
        bottom_touch      : 박스 하단 터치 카운트.
        atr_ratio         : 최근 20일 ATR / 직전 40일 ATR (NaN 가능).
        ma20_slope        : 단기 MA 10일 누적 변화율.
        ma60_slope        : 장기 MA 20일 누적 변화율.
    """

    box_top: float
    box_bottom: float
    range_pct: float
    short_top: float
    short_bottom: float
    short_range_pct: float
    compression_ratio: float
    breakout_idx: int
    top_touch: int
    bottom_touch: int
    atr_ratio: float
    ma20_slope: float
    ma60_slope: float


# ---------------------------------------------------------------------------
# 검증 헬퍼
# ---------------------------------------------------------------------------


def _check_trend_calmness(
    full_df: pd.DataFrame,
    box_end_idx: int,
) -> tuple[bool, dict[str, Any]]:
    """박스 종료 시점의 MA 기울기로 추세 둔화 여부를 검증.

    비대칭 조건:
    - 단기 MA20: -2.5% ~ +3.0% (10일 누적) — 평탄화 요구
    - 장기 MA60: ≥ -2.0% (20일 누적) — 하락만 아니면 OK

    재축적 박스 친화 (장기 우상향 + 단기 평탄화 = 통과).
    하락 추세 끝물 박스 거부 (장기 하락 + 단기 평탄화 = 거부).

    중요 — 입력은 ``full_df`` (전체 데이터). MA60 슬로프 산출에 box_end_idx
    기준으로 ``box_end_idx - 19`` 위치가 필요하고, 그 위치의 SMA60 이 valid
    하려면 box_end_idx >= 78 (= 59 + 19) 이어야 한다. detect 의 _MIN_ROWS
    에서 보장.

    Args:
        full_df    : 전체 일봉 OHLCV (인덱스 reset 가정).
        box_end_idx: 박스 종료(=돌파 직전) 인덱스.

    Returns:
        (passed, details) 튜플.
    """
    close = full_df["close"]
    if box_end_idx < _MAIN_WINDOW - 1:
        return False, {"reason": "box_end_idx_too_small"}

    ma20 = sma(close, 20)
    ma60 = sma(close, 60)

    ma20_now_idx = box_end_idx
    ma20_prev_idx = box_end_idx - (_MA20_SLOPE_WINDOW - 1)
    ma60_now_idx = box_end_idx
    ma60_prev_idx = box_end_idx - (_MA60_SLOPE_WINDOW - 1)

    if ma20_prev_idx < 0 or ma60_prev_idx < 0:
        return False, {"reason": "slope_window_underflow"}
    if pd.isna(ma20.iloc[ma20_now_idx]) or pd.isna(ma20.iloc[ma20_prev_idx]):
        return False, {"reason": "ma20_nan"}
    if pd.isna(ma60.iloc[ma60_now_idx]) or pd.isna(ma60.iloc[ma60_prev_idx]):
        return False, {"reason": "ma60_nan"}
    if ma20.iloc[ma20_prev_idx] == 0 or ma60.iloc[ma60_prev_idx] == 0:
        return False, {"reason": "ma_zero"}

    ma20_slope = float(
        (ma20.iloc[ma20_now_idx] - ma20.iloc[ma20_prev_idx]) / ma20.iloc[ma20_prev_idx]
    )
    ma60_slope = float(
        (ma60.iloc[ma60_now_idx] - ma60.iloc[ma60_prev_idx]) / ma60.iloc[ma60_prev_idx]
    )

    ok_ma20 = _MA20_SLOPE_MIN <= ma20_slope <= _MA20_SLOPE_MAX
    ok_ma60 = ma60_slope >= _MA60_SLOPE_MIN

    return (ok_ma20 and ok_ma60), {
        "ma20_slope": round(ma20_slope, 4),
        "ma60_slope": round(ma60_slope, 4),
        "ok_ma20": ok_ma20,
        "ok_ma60": ok_ma60,
    }


def _calc_atr_compression(
    full_df: pd.DataFrame,
    box_end_idx: int,
) -> float:
    """최근 20일 ATR / 직전 40일 ATR 비율을 반환 (변동성 응축 메트릭).

    가격폭 응축(compression_ratio)과 별개의 차원에서 변동성 자체의
    응축을 측정. 점수 보너스로만 사용 (게이트 아님).

    Args:
        full_df    : 전체 OHLCV.
        box_end_idx: 박스 종료 인덱스 (= 돌파 직전 봉).

    Returns:
        atr_ratio. 데이터 부족이거나 분모 0/NaN 시 NaN.
    """
    if box_end_idx < 60:
        return float("nan")

    atr_series = atr_func(full_df, 14)
    if atr_series.iloc[: box_end_idx + 1].isna().all():
        return float("nan")

    recent = atr_series.iloc[box_end_idx - 19 : box_end_idx + 1].mean()
    base = atr_series.iloc[box_end_idx - 59 : box_end_idx - 19].mean()
    if base == 0 or pd.isna(base) or pd.isna(recent):
        return float("nan")

    return float(recent / base)


def _extract_pivots(
    box_df: pd.DataFrame,
    atr_value: float,
) -> tuple[list[int], list[int]]:
    """메인 박스 구간 내 pivot high / low 인덱스 추출.

    ``scipy.signal.find_peaks`` 사용. ATR 기반 prominence 로 종목별
    변동성 차이를 흡수.

    look-ahead 주의: pivot 은 좌우 _PIVOT_DISTANCE 봉을 본다. 호출 시점에서
    box_df 는 박스 종료(=t-RECENT_DAYS) 까지의 데이터만 들어오므로 미래
    정보 누수 없음.

    Args:
        box_df   : 메인 60일 박스 구간 OHLCV (인덱스 reset 가정).
        atr_value: 해당 종목의 박스 종료 시점 ATR 값.

    Returns:
        (pivot_high_idx, pivot_low_idx) 튜플. 인덱스는 box_df 기준 (0-base).
    """
    if atr_value <= 0 or pd.isna(atr_value):
        return [], []

    prominence = atr_value * _PIVOT_PROMINENCE_ATR_MULT

    high_idx, _ = find_peaks(
        box_df["high"].to_numpy(),
        distance=_PIVOT_DISTANCE,
        prominence=prominence,
    )
    low_idx, _ = find_peaks(
        -box_df["low"].to_numpy(),
        distance=_PIVOT_DISTANCE,
        prominence=prominence,
    )
    return list(high_idx), list(low_idx)


def _dynamic_tolerance(atr_pct: float) -> float:
    """ATR 비율 기반 동적 tolerance.

    저변동 종목엔 강화(1.5%), 고변동 종목엔 완화(3.5%).

    Args:
        atr_pct: ATR / close 비율.

    Returns:
        tolerance 비율 (예: 0.02 = ±2%).
    """
    raw = atr_pct * _TOUCH_TOLERANCE_ATR_MULT
    return max(_TOUCH_TOLERANCE_MIN, min(_TOUCH_TOLERANCE_MAX, raw))


def _count_touches(
    pivot_idx: list[int],
    pivot_prices: pd.Series,
    level: float,
    tolerance: float,
) -> int:
    """level ± tolerance 안에 들어오는 pivot 중 시간 간격 조건을 만족하는 개수.

    같은 가격대를 ``_TOUCH_MIN_GAP_DAYS`` 이내에 연속으로 찍는 경우는
    1회로 카운트 (시장 참여자가 시간을 두고 다시 의식해야 의미 있음).

    Args:
        pivot_idx   : pivot 인덱스 리스트.
        pivot_prices: 인덱스 → 가격 매핑용 Series (box_df['high'] or ['low']).
        level       : 비교 기준 가격 (box_top or box_bottom).
        tolerance   : 허용 오차 비율 (예: 0.02 = ±2%).

    Returns:
        유효 터치 개수.
    """
    if level == 0:
        return 0
    valid: list[int] = []
    for idx in sorted(pivot_idx):
        price = float(pivot_prices.iloc[idx])
        if abs(price - level) / level <= tolerance:
            if not valid or (idx - valid[-1]) >= _TOUCH_MIN_GAP_DAYS:
                valid.append(idx)
    return len(valid)


# ---------------------------------------------------------------------------
# 박스 탐색 (메인 + 단기 응축 분리 검증)
# ---------------------------------------------------------------------------


def _find_best_box(df: pd.DataFrame) -> _BoxInfo | None:
    """메인 60일 박스 + 단기 20일 응축 동시 검증.

    검증 순서 (실패 시 즉시 None):
        1. 메인 60일 박스 폭 ≤ BOX_BREAKOUT_RANGE_PCT (15%)
        2. 단기 20일 박스 폭이 메인의 _SHORT_COMPRESSION_MAX (70%) 이하
        3. 추세 둔화 (MA 기울기 비대칭)
        4. Pivot Touch Count (상단·하단 각 ≥ 2, 시간 분산)
        5. 돌파 발생 (최근 RECENT_DAYS 내 종가 > 상단 * (1 + BREAK_PCT))

    ATR 압축 (atr_ratio) 은 게이트 아니라 점수 보너스로만 사용.

    Args:
        df: 일봉 OHLCV (최신 행이 마지막, 인덱스 reset 가정).

    Returns:
        _BoxInfo (성공) 또는 None.
    """
    n = len(df)
    if n < _MIN_ROWS:
        return None

    df_reset = df.reset_index(drop=True)

    # 박스 종료점 (돌파 직전 봉)
    box_end = n - BOX_BREAKOUT_RECENT_DAYS - 1
    main_start = box_end - _MAIN_WINDOW
    short_start = box_end - _SHORT_WINDOW
    if main_start < 0 or short_start < 0:
        return None

    # ── 1. 메인 60일 박스 폭 ────────────────────────────────
    main_df = df_reset.iloc[main_start : box_end + 1].reset_index(drop=True)
    mean_price = float(main_df["close"].mean())
    if mean_price == 0:
        return None

    box_top = float(main_df["close"].max())
    box_bottom = float(main_df["close"].min())
    range_pct = (box_top - box_bottom) / mean_price

    if range_pct > BOX_BREAKOUT_RANGE_PCT:
        return None

    # ── 2. 단기 20일 응축 ────────────────────────────────────
    short_df = df_reset.iloc[short_start : box_end + 1].reset_index(drop=True)
    short_mean = float(short_df["close"].mean())
    if short_mean == 0:
        return None

    short_top = float(short_df["close"].max())
    short_bottom = float(short_df["close"].min())
    short_range_pct = (short_top - short_bottom) / short_mean

    compression_ratio = short_range_pct / range_pct if range_pct > 0 else 1.0
    if compression_ratio > _SHORT_COMPRESSION_MAX:
        return None

    # ── 3. 추세 둔화 (full_df + box_end_idx 기반 MA 산출) ────
    ok_trend, trend_info = _check_trend_calmness(df_reset, box_end)
    if not ok_trend:
        return None

    # ── ATR 계산 (Pivot prominence + 동적 tolerance + 압축) ─
    atr_series = atr_func(df_reset, 14)
    atr_at_end = atr_series.iloc[box_end]
    atr_now = float(atr_at_end) if not pd.isna(atr_at_end) else 0.0
    last_close_in_box = float(main_df["close"].iloc[-1])
    atr_pct = atr_now / last_close_in_box if last_close_in_box > 0 else 0.02

    atr_ratio = _calc_atr_compression(df_reset, box_end)

    # ── 4. Pivot Touch Count (메인 박스 기준) ───────────────
    pivot_high_idx, pivot_low_idx = _extract_pivots(main_df, atr_now)
    tolerance = _dynamic_tolerance(atr_pct)
    top_touch = _count_touches(pivot_high_idx, main_df["high"], box_top, tolerance)
    bottom_touch = _count_touches(pivot_low_idx, main_df["low"], box_bottom, tolerance)

    if top_touch < _TOUCH_MIN_TOP or bottom_touch < _TOUCH_MIN_BOTTOM:
        return None

    # ── 5. 돌파 발생 검증 ────────────────────────────────────
    recent_df = df_reset.iloc[box_end + 1 :]
    breakout_threshold = box_top * (1 + BOX_BREAKOUT_BREAK_PCT)
    breakout_mask = recent_df["close"] > breakout_threshold
    if not breakout_mask.any():
        return None

    # 가장 최근 돌파일 (RECENT_DAYS 내 다중 발생 시 신선도 우선)
    breakout_idx = int(breakout_mask[breakout_mask].index[-1])

    return _BoxInfo(
        box_top=box_top,
        box_bottom=box_bottom,
        range_pct=range_pct,
        short_top=short_top,
        short_bottom=short_bottom,
        short_range_pct=short_range_pct,
        compression_ratio=compression_ratio,
        breakout_idx=breakout_idx,
        top_touch=top_touch,
        bottom_touch=bottom_touch,
        atr_ratio=atr_ratio,
        ma20_slope=trend_info["ma20_slope"],
        ma60_slope=trend_info["ma60_slope"],
    )


# ---------------------------------------------------------------------------
# 돌파 캔들 품질 헬퍼
# ---------------------------------------------------------------------------


def _calc_break_atr_mult(
    df: pd.DataFrame,
    breakout_idx: int,
    box_top: float,
    atr_now: float,
) -> float:
    """돌파 강도를 ATR 배수로 측정 ((close - box_top) / ATR).

    돌파 1% 가 절대값으로는 같아 보여도, 종목별 ATR 차이로 의미가 다름.
    저변동 종목의 1% 돌파는 강한 신호, 고변동 종목의 1% 돌파는 노이즈 수준.

    Returns:
        ATR 배수. ATR 계산 불가 시 0.0.
    """
    if pd.isna(atr_now) or atr_now <= 0:
        return 0.0
    break_diff = float(df["close"].iloc[breakout_idx]) - box_top
    return break_diff / atr_now


def _check_candle_quality(df: pd.DataFrame, breakout_idx: int) -> bool:
    """돌파 캔들 품질 검증 — 양봉 + 종가가 캔들 60% 위.

    꼬리만 위로 길게 빠지고 종가는 캔들 하단에 마감하는 약한 돌파를
    걸러낸다. 게이트 아닌 점수/메타용.
    """
    o = float(df["open"].iloc[breakout_idx])
    c = float(df["close"].iloc[breakout_idx])
    h = float(df["high"].iloc[breakout_idx])
    l = float(df["low"].iloc[breakout_idx])
    candle_range = h - l
    if candle_range <= 0:
        return False
    return c > o and (c - l) / candle_range >= 0.6


# ---------------------------------------------------------------------------
# 메인 탐지기 클래스
# ---------------------------------------------------------------------------


class BoxBreakoutDetector(PatternDetector):
    """박스권 돌파 패턴 탐지기 (v3).

    CLAUDE.md §5.3 정의를 v3 기준으로 강화:
        - 메인 60일 박스 + 단기 20일 응축 분리 검증
        - 비대칭 추세 둔화 게이트 (재축적 박스 친화)
        - Pivot 기반 터치 카운트 (시장 참여자 의식 강도)
        - ATR 변동성 응축 + 가중 돌파 강도 + 캔들 품질 (점수용)
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
        if len(df) < _MIN_ROWS:
            return None

        df_reset = df.reset_index(drop=True)
        box = _find_best_box(df_reset)
        if box is None:
            return None

        # ── 돌파일 거래량 게이트 ─────────────────────────────────
        vol_ratio_series = volume_ratio(df_reset["volume"])
        cross_vol_ratio = float(vol_ratio_series.iloc[box.breakout_idx])
        if pd.isna(cross_vol_ratio) or cross_vol_ratio < BOX_BREAKOUT_VOLUME_RATIO:
            return None

        # ── 돌파 강도 + 캔들 품질 (점수용 메트릭) ────────────────
        atr_series = atr_func(df_reset, 14)
        atr_at_break = atr_series.iloc[box.breakout_idx]
        atr_now = float(atr_at_break) if not pd.isna(atr_at_break) else 0.0
        break_atr_mult = _calc_break_atr_mult(df_reset, box.breakout_idx, box.box_top, atr_now)
        candle_quality_ok = _check_candle_quality(df_reset, box.breakout_idx)

        # ── 진입가 / 손절 / 목표가 ───────────────────────────────
        last_close = float(df_reset["close"].iloc[-1])
        entry_price = last_close
        stop_loss = box.box_bottom * 0.98          # 박스 하단 -2%
        box_height = box.box_top - box.box_bottom
        target_price = box.box_top + box_height    # measured move (박스 높이만큼)

        risk = entry_price - stop_loss
        reward = target_price - entry_price
        rr = round(reward / risk, 2) if risk > 0 else 0.0

        # ── 점수 (7요소) ─────────────────────────────────────────
        days_since_break = len(df_reset) - 1 - box.breakout_idx
        break_pct = (last_close - box.box_top) / box.box_top if box.box_top != 0 else 0.0

        raw_score = self._calc_raw_score(
            range_pct=box.range_pct,
            compression_ratio=box.compression_ratio,
            vol_ratio=cross_vol_ratio,
            break_pct=break_pct,
            days_since_break=days_since_break,
            top_touch=box.top_touch,
            bottom_touch=box.bottom_touch,
            atr_ratio=box.atr_ratio,
            break_atr_mult=break_atr_mult,
        )

        # ── 탐지 기준일 ──────────────────────────────────────────
        detected_at: date
        if "date" in df.columns:
            detected_at = df["date"].iloc[-1]
            if hasattr(detected_at, "date"):
                detected_at = detected_at.date()
        else:
            detected_at = date.today()

        # ── details (DB·리포트·디버깅) ───────────────────────────
        details: dict[str, Any] = {
            # 윈도우 (참고용)
            "main_window": _MAIN_WINDOW,
            "short_window": _SHORT_WINDOW,
            # 박스 (메인)
            "box_top": round(box.box_top, 4),
            "box_bottom": round(box.box_bottom, 4),
            "range_pct": round(box.range_pct * 100, 4),
            # 박스 (단기 응축)
            "short_top": round(box.short_top, 4),
            "short_bottom": round(box.short_bottom, 4),
            "short_range_pct": round(box.short_range_pct * 100, 4),
            "compression_ratio": round(box.compression_ratio, 4),
            # 돌파
            "breakout_idx": box.breakout_idx,
            "vol_ratio": round(cross_vol_ratio, 4),     # ← scorer 와 키 통일 (v3 fix)
            "break_atr_mult": round(break_atr_mult, 4),
            "candle_quality_ok": candle_quality_ok,
            # 검증 메트릭
            "top_touch": box.top_touch,
            "bottom_touch": box.bottom_touch,
            "atr_ratio": round(box.atr_ratio, 4) if not pd.isna(box.atr_ratio) else None,
            "ma20_slope_pct": round(box.ma20_slope * 100, 4),
            "ma60_slope_pct": round(box.ma60_slope * 100, 4),
            # 메타
            "is_strong_box": (
                box.top_touch >= _STRONG_TOUCH_MIN
                and box.bottom_touch >= _STRONG_TOUCH_MIN
                and box.compression_ratio <= _STRONG_COMPRESSION_MAX
            ),
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

        CLAUDE.md §1 — 4시간봉이 진입 타이밍 프레임. ``above_box_top`` 신호가
        돌파 후 follow-through 의 대리 지표 역할.

        1. RSI 50 돌파 (4시간봉 우선, 없으면 일봉)
        2. 거래량 양봉 (4시간봉 우선)
        3. MACD 히스토그램 양전환 (일봉 — 4h 데이터 부족 시)
        4. 박스 상단 위 유지 (= 돌파 후 되돌림 없음 / follow-through)
        """
        signals: dict[str, bool] = {}
        close = df["close"]
        open_ = df["open"] if "open" in df.columns else close

        # 1. RSI 50 돌파
        rsi_src = intraday_df["close"] if intraday_df is not None else close
        rsi_vals = rsi(rsi_src, 14).dropna()
        if len(rsi_vals) >= 2:
            signals["rsi_above_50"] = (
                float(rsi_vals.iloc[-2]) < 50 and float(rsi_vals.iloc[-1]) > 50
            )
        else:
            signals["rsi_above_50"] = False

        # 2. 거래량 양봉
        vol_src = intraday_df if intraday_df is not None else df
        if "volume" in vol_src.columns and len(vol_src) > 5:
            src_close = float(vol_src["close"].iloc[-1])
            src_open = (
                float(vol_src["open"].iloc[-1]) if "open" in vol_src.columns else src_close
            )
            avg_vol = float(vol_src["volume"].tail(5).mean())
            signals["bullish_volume"] = (
                src_close > src_open and float(vol_src["volume"].iloc[-1]) > avg_vol
            )
        else:
            signals["bullish_volume"] = float(close.iloc[-1]) > float(open_.iloc[-1])

        # 3. MACD 히스토그램 양전환 (일봉)
        if len(close) >= 35:
            _, _, hist = macd(close)
            hist_valid = hist.dropna()
            if len(hist_valid) >= 2:
                signals["macd_positive"] = (
                    float(hist_valid.iloc[-2]) < 0 and float(hist_valid.iloc[-1]) > 0
                )
            else:
                signals["macd_positive"] = False
        else:
            signals["macd_positive"] = False

        # 4. 박스 상단 위 유지 (follow-through 대리)
        df_reset = df.reset_index(drop=True)
        box = _find_best_box(df_reset)
        if box is not None:
            last_close = float(close.iloc[-1])
            signals["above_box_top"] = last_close > box.box_top
        else:
            signals["above_box_top"] = False

        strength = sum(25.0 for v in signals.values() if v)
        return EntrySignal(strength=strength, signals=signals)

    # ── 내부: 점수 계산 ───────────────────────────────────────

    def _calc_raw_score(
        self,
        range_pct: float,
        compression_ratio: float,
        vol_ratio: float,
        break_pct: float,
        days_since_break: int,
        top_touch: int,
        bottom_touch: int,
        atr_ratio: float,
        break_atr_mult: float,
    ) -> float:
        """패턴 명확도 점수 (0~100). scorer 의 pattern_clarity 25% 에 입력.

        v3 7요소 구성:
            - 박스 밀도 (15)        : 메인 60일 박스폭이 작을수록
            - 단기 응축 (15)        : short/main 박스폭 비율이 작을수록 (가격 응축)
            - 변동성 응축 (10)      : atr_ratio 가 작을수록 (변동성 응축)
            - 터치 카운트 (15)      : 시장 참여자 의식 강도
            - 돌파 거래량 (15)      : 자금 유입 강도
            - 돌파 강도 (15)        : ATR 가중 돌파 폭
            - 돌파 신선도 (15)      : 최근일수록
        합계 = 100. ``break_pct`` 는 details 보조용으로 받지만 직접 점수 사용 안 함.
        """
        score = 0.0

        # 박스 밀도 (15)
        density = max(0.0, 1.0 - range_pct / BOX_BREAKOUT_RANGE_PCT)
        score += density * 15

        # 단기 응축 (15) — 0.7 → 0점, 0.4 이하 → 만점
        if compression_ratio <= _SHORT_COMPRESSION_MAX:
            comp_score = max(0.0, min(1.0, (_SHORT_COMPRESSION_MAX - compression_ratio) / 0.3))
            score += comp_score * 15

        # 변동성 응축 (10) — 1.0 → 0점, 0.7 이하 → 만점
        if not pd.isna(atr_ratio):
            atr_compression = max(0.0, min(1.0, (1.0 - atr_ratio) / 0.3))
            score += atr_compression * 10

        # 터치 카운트 (15) — 합산 6회 이상 만점
        touch_total = min(top_touch + bottom_touch, 6)
        score += (touch_total / 6.0) * 15

        # 돌파 거래량 (15) — ratio 1.0 → 0점, 2.0 이상 → 만점
        vol_score = max(0.0, min(1.0, (vol_ratio - 1.0) / 1.0))
        score += vol_score * 15

        # 돌파 강도 (15) — ATR 1배 이상 → 만점
        if break_atr_mult > 0:
            strength = max(0.0, min(1.0, break_atr_mult / 1.0))
            score += strength * 15

        # 돌파 신선도 (15) — 당일 돌파 만점, RECENT_DAYS 끝점 0점
        freshness = max(0.0, 1.0 - days_since_break / BOX_BREAKOUT_RECENT_DAYS)
        score += freshness * 15

        return min(100.0, score)
