"""Scanner CLI 진입점 (STEP 2 이후 구현 예정)."""
from __future__ import annotations

import typer

app = typer.Typer(
    name="scanner",
    help="스윙매매 차트 발굴 시스템 (STEP 2 이후 명령어 추가 예정)",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """현재 버전을 출력한다."""
    from scanner import __version__

    typer.echo(f"swing-scanner {__version__}")


if __name__ == "__main__":
    app()
