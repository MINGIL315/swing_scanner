"""한국(KOSPI/KOSDAQ) 종목 분석 모듈.

데이터 수집(fetcher), 종목 유니버스(universe), 임계값/필터(filters),
지표·패턴·점수 계산, 분석 파이프라인을 모두 포함하는 자체 완결 모듈.

서브모듈:
    kis_api    : KIS(한국투자증권) OpenAPI 클라이언트 (토큰 + 일/주/월봉 + 재무비율)
    fetcher    : 한국 OHLCV/재무 수집 — kis_api 호출 어댑터
    universe   : KOSPI200 구성종목 갱신 (현재 pykrx 사용 — 별도 마이그레이션 대상)
    filters    : 한국 시장 임계값 (거래대금 50억원, PER>0 등)
    indicators : MA, RSI, MACD 등
    patterns   : 4가지 패턴 탐지기
    scoring    : 신뢰도 점수
    backtest   : 백테스트 엔진
    reports    : 리포트
    pipeline   : 한국 종목 분석 흐름
"""
