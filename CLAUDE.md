# CLAUDE.md — Swing Scanner 프로젝트 헌법

> 이 문서는 Claude(또는 어떤 에이전트/협업자)가 이 저장소에서 작업할 때 따라야 할 **불변 규칙**과 **프로젝트 컨텍스트**를 정의한다. 새로운 작업을 시작하기 전에 항상 이 문서를 먼저 읽는다.

## 1. 프로젝트 한 줄 소개

**Swing Scanner**는 한국(코스피200)과 미국(S&P500) 약 700종목을 매일 자동 스캔해 4가지 상승 패턴(쌍바닥·골든크로스·박스권 돌파·눌림목)을 탐지하고, 신뢰도 점수와 진입/손절/목표가를 제시하는 **스윙매매 차트 발굴 시스템**이다.

### 멀티 타임프레임 철학

세 개의 시간 프레임을 **위→아래** 순서로 통과한 종목만 후보로 채택한다.

| 프레임 | 역할 | 판단 기준 |
| --- | --- | --- |
| **주봉** | 큰 추세 확인 | 최근 12주 종가 기울기 + 20주선 위/아래 |
| **일봉** | 패턴 탐지 | 4가지 패턴 정의 |
| **4시간봉(60분봉 4개)** | 진입 타이밍 | 거래량·캔들·RSI 다이버전스 |

→ 주봉이 하락 추세면 일봉에서 패턴이 보여도 **버린다**. 가짜 패턴(=노이즈)을 줄이는 것이 목표.

## 2. 기술 스택

| 카테고리 | 사용 라이브러리/도구 |
| --- | --- |
| 언어 | **Python 3.11+** 권장 (최소 3.10) |
| 데이터 | `pykrx` (한국), `yfinance` (미국) |
| 데이터프레임 | `pandas`, `numpy`, `scipy` |
| DB | **SQLite** + `sqlalchemy` 2.0 |
| API | `fastapi`, `uvicorn[standard]` |
| CLI | `typer`, `rich` |
| 로깅 | `loguru` |
| 리포트 | `jinja2` (HTML), `openpyxl` (Excel) |
| 환경변수 | `python-dotenv` |
| 테스트 | `pytest` |

## 3. 절대 사용하지 않는 것

- ❌ **Docker** — 로컬 스크립트로 충분. 빌드 비용·복잡도만 증가.
- ❌ **PostgreSQL / MySQL** — SQLite로 충분 (단일 사용자, 700 종목 × 수년치 데이터).
- ❌ **Next.js / 프런트엔드 빌드 파이프라인** — Jinja2 + 정적 HTML로 대시보드 구성.
- ❌ **자동매매(주문 API)** — 본 프로젝트는 **차트 발굴 전용**이며, 매매 주문은 사용자가 직접 한다.

## 4. 폴더 구조

```
swing-scanner/
├── scanner/
│   ├── __init__.py
│   ├── config.py                  # 전역 설정 + 임계값 상수
│   ├── kr/                        # 🇰🇷 한국 종목 분석 모듈 — 자체 완결
│   │   ├── fetcher.py             # KOSPI/KOSDAQ OHLCV·재무 (pykrx → 추후 KRX OpenAPI)
│   │   ├── universe.py            # KOSPI200 구성종목 갱신
│   │   ├── scanner.py             # 핵심 분석 (analyze_ticker, scan_universe)
│   │   ├── indicators/            # MA, RSI, MACD 등
│   │   ├── patterns/              # 4가지 패턴 탐지기
│   │   ├── scoring/               # 신뢰도 점수
│   │   ├── filtering/             # 거래량·재무 필터 (한국 임계값)
│   │   ├── backtest/              # 백테스트 엔진
│   │   └── reports/               # HTML/Excel 리포트 (templates/ 포함)
│   ├── us/                        # 🇺🇸 미국 종목 분석 모듈 — 자체 완결
│   │   └── (kr/ 와 동일 구조 — yfinance + 미국 임계값)
│   ├── db/                        # 공통 — SQLAlchemy 모델·세션
│   │   ├── models.py
│   │   ├── session.py
│   │   ├── repository.py
│   │   ├── migrations.py
│   │   └── universe_db.py         # 공용 DB 헬퍼 (get_active_tickers 등)
│   ├── api/                       # 공통 — FastAPI 라우터
│   │   ├── __init__.py
│   │   └── routers/
│   ├── data_pipeline.py           # 통합 데이터 수집 (KR/US 분기)
│   ├── pipeline.py                # cli scan 명령 흐름
│   └── cli.py                     # typer 진입점 (공통)
├── web/                           # 정적 대시보드 자산
├── data/                          # SQLite DB + 캐시 (gitignore)
├── logs/                          # 로그 파일 (gitignore)
├── scripts/                       # 일회성 유틸 스크립트
├── pykrx_api/                     # KRX OpenAPI 명세 PDF (gitignore — 저작권)
└── tests/
    ├── __init__.py
    ├── fixtures/                  # 테스트 픽스처
    ├── data/                      # 시장별 fetcher 테스트
    │   ├── kr/test_fetcher.py
    │   └── us/test_fetcher.py
    └── test_*.py                  # 분석 알고리즘 테스트 (us 모듈 호출)
```

> **시장 분리 정책**: `scanner/kr/` 와 `scanner/us/` 는 **자체 완결 분석 모듈**. 데이터 소스(pykrx vs yfinance), 시장 임계값(거래대금 50억원 vs 5천만 USD), 향후 시장별 알고리즘 차이를 자체 보유. 현재는 동일 코드 복제 상태.
>
> **공통**: `scanner/db/`, `scanner/api/`, `scanner/cli.py`, `scanner/config.py` — DB 모델, FastAPI, CLI dispatcher 는 시장 무관.
>
> **호출 정책**: 양쪽 코드가 동일하므로 cli/pipeline/db/api/backtest 등 일반 호출처는 한쪽(`scanner.kr.X` 또는 `scanner.us.X`)에서 호출. `api/stocks/{ticker}` 만 ticker 추론(`isdigit()`)으로 KR/US 분기. 분석 알고리즘이 시장별로 갈라질 때 명시적 분기로 evolve 가능.

## 5. 4가지 패턴 정의

### 5.1 쌍바닥 (Double Bottom)
- 최근 **60일** 내 ±**3%** 이내의 저점 **2~3개** 형성
- 두 저점 사이의 **목선(고점)** 이 저점 대비 **5% 이상** 위
- 두 번째 저점 형성 후 **목선을 돌파**하는 시점에 신호 발생

### 5.2 골든크로스 (Golden Cross)
- **20일 이동평균선이 60일 이동평균선을 5일 이내**에 상향 돌파
- 60일선이 **평탄(횡보) 또는 상승** 상태 (추세 전환의 진정성)
- 돌파 시점 거래량이 **최근 20일 평균의 1.2배 이상**

### 5.3 박스권 돌파 (Box Breakout)
- 최근 **30~60일** 동안 가격이 **±10%** 박스권에서 횡보
- **최근 1~3일 내**에 박스 상단을 **1% 이상** 돌파
- 돌파일 거래량이 **최근 20일 평균의 1.5배 이상**

### 5.4 눌림목 (Pullback in Uptrend)
- **주봉 추세 = 상승** (필수 조건)
- 일봉 정배열: 5일선 > 20일선 > 60일선
- 현재가가 **20일선 또는 60일선의 ±2% 범위** 안에 위치
- 당일 캔들이 **양봉** (반등 시작 신호)
- 거래량이 최근 5일 평균보다 큼

## 6. 신뢰도 점수 가중치

| 항목 | 가중치 |
| --- | --- |
| 주봉 추세 일치 | **30%** |
| 패턴 명확도 (저점/고점 정렬, 거래량 정확도) | **25%** |
| 거래량 (돌파일 거래량 / 평균) | **20%** |
| 이동평균선 정배열 (5>20>60) | **15%** |
| RSI (30~70 정상 범위, 다이버전스 가점) | **10%** |
| **합계** | **100%** |

> 점수가 70점 이상인 종목만 최종 리포트에 포함한다(임계값은 STEP 6에서 조정 가능).

## 7. 거래량 필터 (Liquidity Filter)

| 시장 | 일평균 거래대금(직전 20일) | 추가 조건 |
| --- | --- | --- |
| 한국 | **50억 원 이상** | 최근 5일 거래량 > 직전 20일 평균 |
| 미국 | **5,000만 USD 이상** | 동일 |

## 8. 재무 필터 (Fundamental Filter)

| 시장 | 시가총액 | PER | 부채비율 |
| --- | --- | --- | --- |
| 한국 | **1,000억 원 이상** | **> 0** (적자 종목 제외) | **< 200%** |
| 미국 | **10억 USD 이상** | **> 0** | (해당 없음 — 데이터 비대칭) |

## 9. 코딩 규칙

- **타입 힌트 필수** — 모든 공개 함수/메서드는 인자/반환 타입을 명시한다 (`from __future__ import annotations` 권장).
- **Docstring은 한국어**로 작성한다. 1줄 요약 + 필요 시 인자/반환 설명.
- **식별자(변수·함수·클래스명)는 영어**, snake_case / PascalCase 표준을 따른다.
- 로깅은 **`loguru`** 만 사용한다. `print()` 금지 (CLI 표시는 `rich.console.Console` 사용).
- 파일 경로는 항상 **`pathlib.Path`** 로 다룬다. 문자열 결합 금지.
- 파일 입출력은 **인코딩 명시 필수**: `open(path, "r", encoding="utf-8")`.
- 외부 데이터 fetch는 반드시 **재시도(`retry_max=3`, exponential backoff)** 와 **타임아웃**을 둔다.
- 함수 하나는 **한 가지 일**만. 100줄을 넘기면 분해를 검토한다.

## 10. Windows 호환성 주의사항

- 콘솔 기본 인코딩은 **cp949**일 수 있다 → 한글 출력에서 UnicodeEncodeError 발생 가능.
  - Python: `sys.stdout.reconfigure(encoding="utf-8")` 또는 `PYTHONIOENCODING=utf-8` 환경변수 사용.
  - `.bat` 스크립트는 **첫 줄에 `chcp 65001`** 을 두어 콘솔을 UTF-8로 전환한다.
- 파일 경로 구분자는 `pathlib.Path`로 정규화 (백슬래시 하드코딩 금지).
- `pykrx`는 KRX 서버에 의존 → 휴장일/장중 호출 시 빈 DataFrame을 반환할 수 있음. 항상 빈 결과 검증.

## 11. Git 워크플로우

### 브랜치 명명
- `feat/step-N-이름` — STEP 단위 기능 추가
- `fix/이슈요약` — 버그 수정
- `docs/문서수정` — 문서 변경만
- `refactor/대상` — 동작 변경 없는 리팩터
- `perf/대상` — 성능 개선

### 커밋 메시지 — Conventional Commits

```
<type>(<scope>): <한국어 본문>
```

타입: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`

예시:
- `feat(patterns): 쌍바닥 탐지기 구현`
- `fix(data): pykrx 빈 DataFrame 처리 누락`
- `docs: README 빠른 시작 섹션 갱신`

### STEP 단위 커밋 분할
- 한 STEP은 **의미 단위 5~15개 커밋**으로 분할한다.
- 큰 변경을 한 커밋에 몰지 않는다 (리뷰·롤백 비용 증가).

### STEP 완료 시
1. 모든 커밋을 푸시
2. PR 생성 (`base=main`, `head=feat/step-N-...`)
3. **squash 머지** + 브랜치 삭제
4. 태그 부여 (`step-N-complete`) + 푸시

## 12. CLI 최종 형태 (목표)

```bash
scanner scan                        # 오늘자 스캔 (KR + US)
scanner scan --market KR
scanner scan --pattern double_bottom
scanner report --date 2026-05-04   # HTML 리포트 생성
scanner report --format excel
scanner backtest --pattern golden_cross --from 2024-01-01 --to 2025-12-31
scanner serve                       # FastAPI 대시보드 (127.0.0.1:8000)
scanner version
```

## 13. 투자 면책 조항 (Disclaimer)

> 본 시스템은 **개인 투자자의 학습·연구·차트 발굴 보조** 목적으로 제작되었으며, 어떠한 매매 권유나 수익 보장도 하지 않는다.
>
> 출력되는 점수·진입가·손절가·목표가는 **과거 데이터 기반의 통계적 추정**이며, 실제 매매 결과를 보장하지 않는다.
>
> 모든 매매 의사결정과 그 결과(이익·손실 모두)는 **사용자 본인의 책임**이다.
>
> 본 시스템을 사용하기 전 자신의 투자 성향·자금 사정·세금·법적 제약을 충분히 검토하라.
