"""4h resample 진단 — drop_partial=True 가 비어있게 되는 원인 파악."""
from __future__ import annotations

from datetime import date, datetime, time as time_t, timedelta

import pandas as pd
from sqlalchemy import select

from scanner.db.models import OHLCVIntraday
from scanner.db.session import get_session
from scanner.kr.intraday import resample_to_4h, resample_to_60min


def diag_ticker(ticker: str) -> None:
    cutoff = datetime.combine(date.today() - timedelta(days=30), time_t.min)
    with get_session() as session:
        rows = list(
            session.execute(
                select(OHLCVIntraday)
                .where(OHLCVIntraday.ticker == ticker)
                .where(OHLCVIntraday.datetime >= cutoff)
                .order_by(OHLCVIntraday.datetime)
            ).scalars().all()
        )

    if not rows:
        print(f"{ticker}: 분봉 데이터 0건")
        return

    df = pd.DataFrame([
        {
            "ticker": r.ticker,
            "datetime": r.datetime,
            "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume,
        }
        for r in rows
    ])

    print(f"=== {ticker} 분봉 진단 ===")
    print(f"총 1분봉 갯수: {len(df)}")
    print(f"기간: {df['datetime'].min()} ~ {df['datetime'].max()}")

    # 일자별 카운트
    df["date"] = pd.to_datetime(df["datetime"]).dt.date
    by_day = df.groupby("date").size()
    print(f"일자별 1분봉 갯수 (최근 5일):")
    for d, c in by_day.tail(5).items():
        print(f"  {d}: {c}봉")

    # 4h resample drop_partial=False
    df_4h_all = resample_to_4h(df, drop_partial=False)
    print(f"\n4h resample (drop_partial=False): {len(df_4h_all)}봉")
    if not df_4h_all.empty:
        for _, row in df_4h_all.tail(6).iterrows():
            print(f"  {row['datetime']}  O={row['open']} H={row['high']} L={row['low']} C={row['close']} V={row['volume']}")

    # 4h resample drop_partial=True
    df_4h_full = resample_to_4h(df, drop_partial=True)
    print(f"\n4h resample (drop_partial=True): {len(df_4h_full)}봉")
    if not df_4h_full.empty:
        for _, row in df_4h_full.tail(6).iterrows():
            print(f"  {row['datetime']}  O={row['open']} H={row['high']} L={row['low']} C={row['close']} V={row['volume']}")

    # 60min resample drop_partial=True (이전 작동 확인)
    df_60 = resample_to_60min(df, drop_partial=True)
    print(f"\n60min resample (drop_partial=True): {len(df_60)}봉")


if __name__ == "__main__":
    diag_ticker("018880")
