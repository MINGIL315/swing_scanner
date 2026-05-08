"""데이터 수집 계층 — 유니버스 관리, KR/US fetcher, 통합 파이프라인.

서브모듈:
    scanner.data.kr.fetcher    : 한국 OHLCV/재무 수집 (pykrx)
    scanner.data.kr.universe   : KOSPI200 구성종목 갱신
    scanner.data.us.fetcher    : 미국 OHLCV/재무 수집 (yfinance)
    scanner.data.us.universe   : S&P500 구성종목 갱신
    scanner.data.universe      : 공용 DB 헬퍼 (get_active_tickers, _upsert_tickers)
    scanner.data.pipeline      : 통합 파이프라인 (run_data_pipeline 등)

호출자는 필요한 서브모듈을 명시적으로 임포트해서 사용한다.
"""
