"""KR 종목의 DB 적재 현황 점검.

universe / ohlcv_daily / ohlcv_weekly / fundamentals 테이블의 KR 종목 행 수와
종목 커버리지를 출력한다.

실행:
    .venv/Scripts/python.exe scripts/check_kr_data.py
"""
from __future__ import annotations

from sqlalchemy import func, select

from scanner.db.models import Fundamental, OHLCVDaily, OHLCVWeekly, Universe
from scanner.db.session import get_session


def main() -> None:
    with get_session() as sess:
        kr_tickers = [
            r[0]
            for r in sess.execute(
                select(Universe.ticker).where(Universe.market == "KR")
            ).all()
        ]

        n_daily = sess.execute(
            select(func.count(OHLCVDaily.id)).where(OHLCVDaily.ticker.in_(kr_tickers))
        ).scalar_one()
        n_weekly = sess.execute(
            select(func.count(OHLCVWeekly.id)).where(OHLCVWeekly.ticker.in_(kr_tickers))
        ).scalar_one()
        n_fund = sess.execute(
            select(func.count(Fundamental.id)).where(Fundamental.ticker.in_(kr_tickers))
        ).scalar_one()
        n_daily_tickers = sess.execute(
            select(func.count(func.distinct(OHLCVDaily.ticker))).where(
                OHLCVDaily.ticker.in_(kr_tickers)
            )
        ).scalar_one()
        n_fund_tickers = sess.execute(
            select(func.count(func.distinct(Fundamental.ticker))).where(
                Fundamental.ticker.in_(kr_tickers)
            )
        ).scalar_one()

        # OHLCV 일자 범위
        date_min, date_max = sess.execute(
            select(func.min(OHLCVDaily.date), func.max(OHLCVDaily.date)).where(
                OHLCVDaily.ticker.in_(kr_tickers)
            )
        ).one()

    print("=== KR 데이터 적재 현황 ===")
    print(f"  Universe (활성)        : {len(kr_tickers)} 종목")
    print(f"  OHLCV daily            : {n_daily:,} 행, {n_daily_tickers} 종목 보유")
    print(f"  OHLCV weekly           : {n_weekly:,} 행")
    print(f"  Fundamental            : {n_fund} 행, {n_fund_tickers} 종목 보유")
    print(f"  OHLCV daily 일자 범위 : {date_min} ~ {date_max}")

    print()
    if n_daily_tickers < len(kr_tickers):
        missing = len(kr_tickers) - n_daily_tickers
        print(f"⚠️  OHLCV daily 누락 종목: {missing} 종목")
    else:
        print("✓ OHLCV daily 모든 종목 보유")

    if n_fund_tickers < len(kr_tickers):
        missing = len(kr_tickers) - n_fund_tickers
        print(f"⚠️  Fundamental 누락 종목: {missing} 종목")
    else:
        print("✓ Fundamental 모든 종목 보유")


if __name__ == "__main__":
    main()
