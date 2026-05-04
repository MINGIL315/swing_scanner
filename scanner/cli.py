"""Scanner CLI 진입점."""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="scanner",
    help="스윙매매 차트 발굴 시스템",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """현재 버전을 출력한다."""
    from scanner import __version__

    typer.echo(f"swing-scanner {__version__}")


@app.command("update-universe")
def update_universe(
    market: str = typer.Option(
        "all",
        "--market",
        "-m",
        help="갱신할 시장: kr | us | all",
    ),
) -> None:
    """종목 유니버스를 최신 구성종목으로 갱신한다.

    kr  → KOSPI200 (pykrx)\n
    us  → S&P500   (Wikipedia)\n
    all → 둘 다
    """
    from scanner.config import setup_logger
    from scanner.data.universe import update_kospi200, update_sp500
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    m = market.upper()
    if m in ("KR", "ALL"):
        count = update_kospi200()
        console.print(f"[green]KOSPI200[/green] {count} 종목 갱신 완료")
    if m in ("US", "ALL"):
        count = update_sp500()
        console.print(f"[green]S&P500[/green] {count} 종목 갱신 완료")
    if m not in ("KR", "US", "ALL"):
        console.print(f"[red]알 수 없는 시장: {market} (kr / us / all 중 선택)[/red]")
        raise typer.Exit(code=1)


@app.command("fetch")
def fetch(
    ticker: str = typer.Argument(..., help="종목 코드 (예: 005930, AAPL)"),
    days: int = typer.Option(365, "--days", "-d", help="과거 몇 일치 데이터 수집"),
) -> None:
    """단일 종목의 OHLCV + 재무 데이터를 수집한다."""
    from datetime import date, timedelta

    from scanner.config import setup_logger
    from scanner.data.pipeline import (
        _fetch_fundamental_one,
        _fetch_ohlcv_one,
        _get_market,
    )
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    today = date.today()
    start = today - timedelta(days=days)
    market = _get_market(ticker)

    console.print(f"[cyan]{ticker}[/cyan] ({market}) OHLCV 수집 중...")
    _, ok_o, err_o = _fetch_ohlcv_one(ticker, market, start, today)
    if ok_o:
        console.print(f"[green]OHLCV 완료[/green]")
    else:
        console.print(f"[red]OHLCV 실패: {err_o}[/red]")

    console.print(f"[cyan]{ticker}[/cyan] 재무 수집 중...")
    _, ok_f, err_f = _fetch_fundamental_one(ticker, market, today)
    if ok_f:
        console.print(f"[green]재무 완료[/green]")
    else:
        console.print(f"[red]재무 실패: {err_f}[/red]")


@app.command("fetch-all")
def fetch_all(
    market: str = typer.Option(
        "all",
        "--market",
        "-m",
        help="수집할 시장: kr | us | all",
    ),
    days: int = typer.Option(365, "--days", "-d", help="과거 몇 일치 데이터 수집"),
) -> None:
    """모든 활성 종목의 OHLCV + 재무 데이터를 일괄 수집한다."""
    from datetime import date, timedelta

    from scanner.config import setup_logger
    from scanner.data.pipeline import run_data_pipeline
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    today = date.today()
    start = today - timedelta(days=days)
    run_data_pipeline(market=market.upper(), start=start, end=today)


if __name__ == "__main__":
    app()
