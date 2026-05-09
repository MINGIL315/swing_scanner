"""KR 종목의 DB 적재 현황 점검.

universe / ohlcv_daily / ohlcv_weekly / fundamentals 테이블의 KR 종목 행 수와
종목 커버리지를 출력한다.

실행:
    .venv/Scripts/python.exe scripts/check_kr_data.py
"""
from __future__ import annotations

from sqlalchemy import func, select

from scanner.db.models import (
    Fundamental,
    OHLCVDaily,
    OHLCVIntraday,
    OHLCVWeekly,
    Universe,
)
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

        # 분봉 (1분봉) 통계
        n_intraday = sess.execute(
            select(func.count(OHLCVIntraday.id)).where(
                OHLCVIntraday.ticker.in_(kr_tickers)
            )
        ).scalar_one()
        n_intraday_tickers = sess.execute(
            select(func.count(func.distinct(OHLCVIntraday.ticker))).where(
                OHLCVIntraday.ticker.in_(kr_tickers)
            )
        ).scalar_one()
        intraday_min, intraday_max = sess.execute(
            select(func.min(OHLCVIntraday.datetime), func.max(OHLCVIntraday.datetime)).where(
                OHLCVIntraday.ticker.in_(kr_tickers)
            )
        ).one()
        n_intraday_dates = sess.execute(
            select(func.count(func.distinct(func.date(OHLCVIntraday.datetime)))).where(
                OHLCVIntraday.ticker.in_(kr_tickers)
            )
        ).scalar_one()

    print("=== KR 데이터 적재 현황 ===")
    print(f"  Universe (활성)        : {len(kr_tickers)} 종목")
    print(f"  OHLCV daily            : {n_daily:,} 행, {n_daily_tickers} 종목 보유")
    print(f"  OHLCV weekly           : {n_weekly:,} 행")
    print(f"  OHLCV intraday(1분봉)  : {n_intraday:,} 행, {n_intraday_tickers} 종목, {n_intraday_dates} 영업일")
    print(f"  Fundamental            : {n_fund} 행, {n_fund_tickers} 종목 보유")
    print(f"  OHLCV daily 일자 범위 : {date_min} ~ {date_max}")
    if intraday_min:
        print(f"  Intraday 시각 범위    : {intraday_min} ~ {intraday_max}")

    print()
    if n_daily_tickers < len(kr_tickers):
        missing = len(kr_tickers) - n_daily_tickers
        print(f"⚠️  OHLCV daily 누락 종목: {missing} 종목")
    else:
        print("✓ OHLCV daily 모든 종목 보유")

    if n_intraday_tickers < len(kr_tickers):
        missing = len(kr_tickers) - n_intraday_tickers
        print(f"⚠️  Intraday 누락 종목: {missing} 종목 (휴장일/미상장 정상 가능)")
    else:
        print(f"✓ Intraday 모든 종목 보유 (종목당 평균 {n_intraday // max(n_intraday_tickers, 1):,}행)")

    if n_fund_tickers < len(kr_tickers):
        missing = len(kr_tickers) - n_fund_tickers
        print(f"⚠️  Fundamental 누락 종목: {missing} 종목")
    else:
        print("✓ Fundamental 모든 종목 보유")


if __name__ == "__main__":
    main()
