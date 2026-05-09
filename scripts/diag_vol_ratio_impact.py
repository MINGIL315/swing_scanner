"""vol_ratio 키 수정의 영향 진단 — 변경 전 60~70점 종목 중 70+ 새 통과 종목 추출.

변경 전: scorer 가 details.get('vol_ratio', 0.0) → 3 패턴 거래량 점수 항상 0
변경 후: details['vol_ratio'] alias 추가 → 정상 산출

같은 detect 결과를 두 가지 ScoringInput 으로 산출 (변경 전 시뮬은 vol_ratio 제거).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from scanner.db.models import OHLCVDaily, Universe
from scanner.db.session import get_session
from scanner.kr.patterns import ALL_DETECTORS
from scanner.kr.patterns.pullback import _resample_weekly
from scanner.kr.patterns.trend import detect_weekly_trend
from scanner.kr.scoring.scorer import ScoringInput, calculate_confidence_score


THRESHOLD = 70.0


def _kr_tickers() -> list[str]:
    with get_session() as session:
        return [
            t for (t,) in session.execute(
                select(Universe.ticker)
                .where(Universe.market == "KR")
                .where(Universe.is_active.is_(True))
            ).all()
        ]


def _load_daily(ticker: str, lookback_days: int = 500) -> pd.DataFrame:
    start = date.today() - timedelta(days=lookback_days)
    with get_session() as session:
        rows = list(
            session.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.ticker == ticker)
                .where(OHLCVDaily.date >= start)
                .order_by(OHLCVDaily.date)
            ).scalars().all()
        )
    return pd.DataFrame([
        {"date": r.date, "open": r.open, "high": r.high, "low": r.low,
         "close": r.close, "volume": r.volume}
        for r in rows
    ])


def _score_with_vol_ratio_zero(pr, weekly_dir: str, weekly_strength: float, df) -> float:
    """vol_ratio 키 제거 → scorer 가 default 0.0 사용 → 변경 전 시뮬."""
    old_details = dict(pr.details)
    old_details.pop("vol_ratio", None)
    old_pr = replace(pr, details=old_details)
    inp = ScoringInput(
        pattern_result=old_pr,
        weekly_trend_direction=weekly_dir,
        weekly_trend_strength=weekly_strength,
        daily_df=df,
    )
    return calculate_confidence_score(inp)


def main() -> None:
    tickers = _kr_tickers()
    print(f"=== vol_ratio 수정 전후 점수 비교 (KOSPI200 {len(tickers)}종목, threshold={THRESHOLD}) ===\n")

    new_passed = []   # 변경 후 새로 통과 (old < 70 ≤ new)
    same_passed = []  # 둘 다 통과
    same_failed = []  # 둘 다 탈락 (또는 detect 실패)
    detected_count = 0

    for t in tickers:
        df = _load_daily(t)
        if df.empty:
            continue

        try:
            weekly_df = _resample_weekly(df)
            trend = detect_weekly_trend(weekly_df)
            weekly_dir, weekly_strength = trend.direction, trend.strength
        except Exception:
            weekly_dir, weekly_strength = "sideways", 0.0

        for det in ALL_DETECTORS:
            try:
                pr = det.detect(df, t)
            except Exception:
                continue
            if pr is None:
                continue
            detected_count += 1

            new_inp = ScoringInput(
                pattern_result=pr,
                weekly_trend_direction=weekly_dir,
                weekly_trend_strength=weekly_strength,
                daily_df=df,
            )
            new_score = calculate_confidence_score(new_inp)
            old_score = _score_with_vol_ratio_zero(pr, weekly_dir, weekly_strength, df)

            entry = (t, det.name, old_score, new_score, pr.details.get("vol_ratio"))

            if old_score < THRESHOLD <= new_score:
                new_passed.append(entry)
            elif old_score >= THRESHOLD and new_score >= THRESHOLD:
                same_passed.append(entry)
            else:
                same_failed.append(entry)

    print(f"전체 detect 통과: {detected_count}건")
    print(f"  변경 후 새로 70+ 통과:  {len(new_passed)}건  ← 핵심 영향")
    print(f"  둘 다 70+ 통과:        {len(same_passed)}건")
    print(f"  둘 다 70 미만:         {len(same_failed)}건")
    print()

    if new_passed:
        print(f"새로 통과한 종목/패턴 (정렬: 신규 점수 내림차순):")
        new_passed.sort(key=lambda x: -x[3])
        print(f"  {'ticker':8s} {'pattern':14s}  {'old':>5s}  {'new':>5s}  {'+ Δ':>5s}  vol_ratio")
        for ticker, pname, old, new, vr in new_passed:
            vr_str = f"{vr:.2f}" if vr is not None else "—"
            print(f"  {ticker:8s} {pname:14s}  {old:5.1f}  {new:5.1f}  {new-old:+5.1f}  {vr_str}")

        print(f"\n패턴별 새로 통과 갯수:")
        by_pattern = Counter(x[1] for x in new_passed)
        for p, c in by_pattern.most_common():
            print(f"  {p}: {c}건")

    # 둘 다 통과한 종목의 점수 상승폭 통계
    if same_passed:
        diffs = sorted([x[3] - x[2] for x in same_passed])
        nd = len(diffs)
        print(f"\n둘 다 통과 종목의 점수 상승폭 ({nd}건):")
        print(f"  min={min(diffs):+.1f}  med={diffs[nd//2]:+.1f}  max={max(diffs):+.1f}")


if __name__ == "__main__":
    main()
