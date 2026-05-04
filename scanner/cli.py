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


@app.command("test-pattern")
def test_pattern(
    ticker: str = typer.Argument(..., help="종목 코드 (예: 005930, AAPL)"),
    pattern: Optional[str] = typer.Option(
        None,
        "--pattern",
        "-p",
        help="패턴 이름: double_bottom | golden_cross | box_breakout | pullback (기본: 전체)",
    ),
    days: int = typer.Option(500, "--days", "-d", help="최근 N일 데이터 로드"),
) -> None:
    """특정 종목에 패턴 탐지기를 실행해 디버그 결과를 출력한다."""
    from datetime import date, timedelta

    from rich.table import Table

    from scanner.config import setup_logger
    from scanner.data.pipeline import _fetch_ohlcv_one, _get_market
    from scanner.db.migrations import init_database
    from scanner.db.session import get_session
    from scanner.db.models import OHLCVDaily
    from scanner.patterns import ALL_DETECTORS, get_detector

    setup_logger()
    init_database()

    # ── 데이터 로드 ────────────────────────────────────────────────
    # DB 에서 먼저 시도, 없으면 직접 수집
    import pandas as pd
    from sqlalchemy import select

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    with get_session() as session:
        rows = session.execute(
            select(OHLCVDaily)
            .where(OHLCVDaily.ticker == ticker)
            .where(OHLCVDaily.date >= start_date)
            .order_by(OHLCVDaily.date)
        ).scalars().all()

    if rows:
        df = pd.DataFrame([
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ])
        console.print(f"[dim]DB에서 {len(df)}행 로드[/dim]")
    else:
        console.print(f"[yellow]DB 데이터 없음. {ticker} 직접 수집 중...[/yellow]")
        market = _get_market(ticker)
        result_tuple = _fetch_ohlcv_one(ticker, market, start_date, end_date)
        if not result_tuple[1]:
            console.print(f"[red]데이터 수집 실패: {result_tuple[2]}[/red]")
            raise typer.Exit(code=1)
        # 수집 후 DB 재조회
        with get_session() as session:
            rows = session.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.ticker == ticker)
                .where(OHLCVDaily.date >= start_date)
                .order_by(OHLCVDaily.date)
            ).scalars().all()
        df = pd.DataFrame([
            {"date": r.date, "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume}
            for r in rows
        ])
        console.print(f"[dim]수집 후 {len(df)}행 로드[/dim]")

    if df.empty:
        console.print("[red]데이터가 없습니다.[/red]")
        raise typer.Exit(code=1)

    # ── 탐지기 선택 ────────────────────────────────────────────────
    if pattern:
        detector = get_detector(pattern)
        if detector is None:
            valid = ", ".join(d.name for d in ALL_DETECTORS)
            console.print(f"[red]알 수 없는 패턴: {pattern}. 가능한 값: {valid}[/red]")
            raise typer.Exit(code=1)
        detectors = [detector]
    else:
        detectors = ALL_DETECTORS

    # ── 패턴 탐지 실행 ─────────────────────────────────────────────
    found_any = False
    for det in detectors:
        console.rule(f"[bold]{det.display_name}[/bold] ({det.name})")
        result = det.detect(df, ticker)
        if result is None:
            console.print("[yellow]  → 탐지되지 않음[/yellow]")
            continue

        found_any = True
        sig = det.entry_signal(df)

        tbl = Table(show_header=False, padding=(0, 1))
        tbl.add_column("항목", style="cyan")
        tbl.add_column("값")

        tbl.add_row("탐지일", str(result.detected_at))
        tbl.add_row("진입가", f"{result.entry_price:,.4f}")
        tbl.add_row("손절가", f"{result.stop_loss:,.4f}")
        tbl.add_row("목표가", f"{result.target_price:,.4f}")
        tbl.add_row("손익비", str(result.risk_reward_ratio))
        tbl.add_row("패턴 점수", f"{result.raw_score:.1f} / 100")
        tbl.add_row("진입 강도", f"{sig.strength:.0f} / 100")
        for sig_name, sig_val in sig.signals.items():
            mark = "[green]✓[/green]" if sig_val else "[red]✗[/red]"
            tbl.add_row(f"  {sig_name}", mark)
        for k, v in result.details.items():
            tbl.add_row(f"  {k}", str(v))

        console.print(tbl)

    if not found_any:
        console.print("\n[bold yellow]탐지된 패턴 없음[/bold yellow]")


if __name__ == "__main__":
    app()
