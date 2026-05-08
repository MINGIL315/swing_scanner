"""미국(NYSE/NASDAQ) 종목 분석 모듈.

데이터 수집(fetcher), 종목 유니버스(universe), 임계값/필터(filters),
지표·패턴·점수 계산, 분석 파이프라인을 모두 포함하는 자체 완결 모듈.

서브모듈:
    fetcher    : 미국 OHLCV/재무 수집 (yfinance)
    universe   : S&P500 구성종목 갱신
    filters    : 미국 시장 임계값 (거래대금 5천만 USD 등)
    indicators : MA, RSI, MACD 등 (Phase 2 에서 복제)
    patterns   : 4가지 패턴 탐지기 (Phase 2)
    scoring   : 신뢰도 점수 (Phase 2)
    backtest   : 백테스트 엔진 (Phase 2)
    reports    : 리포트 (Phase 2)
    pipeline   : 미국 종목 분석 흐름 (Phase 2)
"""
