"""KIS 종목 마스터의 KOSPI200섹터업종 필드 진단 (일회성).

대표 KOSPI200 종목의 sector 값을 출력하고, 전체 sector 값 분포 및
단축코드 길이 분포를 보여 KOSPI200 멤버십 식별 누락 원인을 찾는다.

실행:
    .venv/Scripts/python.exe scripts/diagnose_kospi_master.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from scanner.kr.kis_master import (
    download_kospi_master_mst,
    parse_kospi_master_dataframe,
)


SAMPLES: list[tuple[str, str]] = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("035720", "카카오"),
    ("000270", "기아"),
    ("051910", "LG화학"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("012330", "현대모비스"),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        mst = download_kospi_master_mst(Path(td))
        df = parse_kospi_master_dataframe(mst)

    df["t"] = df["단축코드"].astype(str).str.strip()
    df["s"] = df["KOSPI200섹터업종"].astype(str).str.strip()
    df["n"] = df["한글명"].astype(str).str.strip()

    print("=== 대표 KOSPI200 종목 sector 값 ===")
    for ticker, expected_name in SAMPLES:
        rows = df[df["t"] == ticker]
        if rows.empty:
            print(f"  {ticker}  {expected_name:<12s} : 마스터에 없음")
        else:
            row = rows.iloc[0]
            print(f"  {ticker}  {row['n']:<12s} sector={row['s']!r}")

    print()
    print("=== 전체 'KOSPI200섹터업종' 값 분포 (상위 15) ===")
    print(df["s"].value_counts().head(15))

    print()
    print("=== 단축코드 길이 분포 ===")
    print(df["t"].str.len().value_counts().sort_index())


if __name__ == "__main__":
    main()
