"""오늘자 ScanResult 의 entry_signal_strength 분포 확인."""
from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import select

from scanner.db.models import ScanResult
from scanner.db.session import get_session


def main() -> None:
    today = date.today()
    with get_session() as session:
        rows = list(
            session.execute(
                select(ScanResult)
                .where(ScanResult.scan_date == today)
                .order_by(ScanResult.confidence_score.desc())
            ).scalars().all()
        )

    if not rows:
        print(f"{today} 결과 없음")
        return

    print(f"=== {today} ScanResult ({len(rows)} 건) ===\n")
    # strength 분포
    strengths = [r.entry_signal_strength for r in rows if r.entry_signal_strength is not None]
    null_count = sum(1 for r in rows if r.entry_signal_strength is None)
    print(f"strength 통계 (non-null {len(strengths)}건, null {null_count}건):")
    if strengths:
        print(f"  min={min(strengths):.1f}  max={max(strengths):.1f}  avg={sum(strengths)/len(strengths):.1f}")
        bucket = Counter(int(s // 25) * 25 for s in strengths)
        for b in sorted(bucket):
            print(f"  {b:>3}~{b+24}: {bucket[b]}건")

    # 신호별 발화 빈도
    print("\n신호별 발화 빈도:")
    sig_counter: Counter[str] = Counter()
    sig_total: Counter[str] = Counter()
    for r in rows:
        sigs = r.entry_signals or {}
        for k, v in sigs.items():
            sig_total[k] += 1
            if v:
                sig_counter[k] += 1
    for k in sig_total:
        cnt = sig_counter[k]
        tot = sig_total[k]
        print(f"  {k:20s} {cnt}/{tot}  ({cnt/tot*100:.0f}%)")

    print("\nTOP 10 — entry_signal_strength 포함:")
    print(f"{'#':>3} {'ticker':8s} {'pattern':14s} {'score':>5} {'strength':>8}  signals")
    for i, r in enumerate(rows[:10], 1):
        sigs = r.entry_signals or {}
        sig_str = " ".join(f"{k}={'V' if v else '.'}" for k, v in sigs.items())
        s = r.entry_signal_strength
        s_str = f"{s:.0f}" if s is not None else "null"
        print(f"{i:>3} {r.ticker:8s} {r.pattern_name:14s} {r.confidence_score:5.1f} {s_str:>8}  {sig_str}")


if __name__ == "__main__":
    main()
