# Swing Scanner

한국(코스피200)과 미국(S&P500) 약 700종목을 매일 자동 스캔해 4가지 상승 패턴(쌍바닥·골든크로스·박스권 돌파·눌림목)을 탐지하고, 신뢰도 점수와 진입/손절/목표가를 제시하는 **스윙매매 차트 발굴 시스템**입니다. 주봉(추세) → 일봉(패턴) → 4시간봉(타이밍)의 멀티 타임프레임으로 가짜 신호를 거릅니다.

> 프로젝트의 모든 규칙·임계값·구조는 [`CLAUDE.md`](./CLAUDE.md)에 정의되어 있습니다.

## 사전 요구사항

- **Python 3.10 이상** (3.11+ 권장)
- **Git**
- Windows 10/11, macOS, Linux 모두 지원하나 일차 타깃은 **Windows**

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/MINGIL315/swing_scanner.git
cd swing_scanner

# 2. 가상환경 생성 + 활성화
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 3. 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .                   # scanner CLI를 PATH에 등록

# 4. 환경 변수 (선택)
cp .env.example .env               # Windows: copy .env.example .env

# 5. DB 초기화
python -m scanner.db.migrations
```

DB 초기화에 성공하면 `data/scanner.db` 파일이 생성되고 7개 테이블이 만들어집니다.
다음으로 확인:

```bash
sqlite3 data/scanner.db ".tables"
# 출력:
# backtest_results  fundamentals     ohlcv_intraday    scan_results
# ohlcv_daily       ohlcv_weekly     universe
```

## 빠른 시작

> **현재 STEP 1까지만 완료된 상태입니다.** 데이터 수집·패턴 탐지·리포트는 이후 STEP에서 추가됩니다.

지금 사용 가능한 명령:

```bash
scanner version          # 패키지 버전 확인
python -m scanner.db.migrations   # DB 재초기화 (idempotent)
```

## 향후 추가될 기능 (로드맵)

| STEP | 내용 |
| --- | --- |
| **STEP 2** | 데이터 수집 어댑터 (`pykrx`, `yfinance`) + Universe 빌더 |
| **STEP 3** | 일봉/주봉/60분봉 캐시 + 증분 업데이트 + 거래량/재무 필터 |
| **STEP 4** | 기술적 지표 (MA, RSI, 볼린저, 거래량 가중) |
| **STEP 5** | 4가지 패턴 탐지기 (쌍바닥·골든크로스·박스권 돌파·눌림목) |
| **STEP 6** | 신뢰도 점수 엔진 + 진입/손절/목표가 산출 |
| **STEP 7** | 백테스트 엔진 + 패턴별 승률·손익비 측정 |
| **STEP 8** | HTML/Excel/CSV 리포트 + FastAPI 로컬 대시보드 |

각 STEP은 독립적인 PR로 머지되며 `step-N-complete` 태그로 마감됩니다.

## 폴더 구조 (요약)

```
scanner/         # 본체 패키지
  config.py      # 임계값·가중치·필터 상수
  db/            # SQLAlchemy 모델·세션·마이그레이션
  data/          # (예정) pykrx/yfinance 어댑터
  indicators/    # (예정) 기술적 지표
  patterns/      # (예정) 패턴 탐지
  scoring/       # (예정) 신뢰도 점수
  filtering/     # (예정) 거래량·재무 필터
  backtest/      # (예정) 백테스트
  reports/       # (예정) HTML/Excel/CSV
  api/           # (예정) FastAPI 라우터
  cli.py         # typer CLI 진입점
data/            # SQLite DB · 캐시 (gitignore)
logs/            # 로그 파일 (gitignore)
tests/           # pytest
```

## 개발 규칙

- 커밋 메시지: **Conventional Commits** (`feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`)
- 브랜치: `feat/step-N-이름`, `fix/이슈요약`
- 한 STEP = 5~15개 의미 단위 커밋 → PR → squash 머지 → 태그
- 코드 스타일: 타입 힌트 필수, 한국어 docstring, 영어 식별자
- 자세한 규칙은 [`CLAUDE.md`](./CLAUDE.md) 참조

## 면책 조항 (Disclaimer)

본 시스템은 **개인 투자자의 학습·연구·차트 발굴 보조** 목적으로 제작되었으며, 어떠한 매매 권유나 수익 보장도 하지 않습니다.

출력되는 점수·진입가·손절가·목표가는 **과거 데이터 기반의 통계적 추정**이며, 실제 매매 결과를 보장하지 않습니다.

모든 매매 의사결정과 그 결과(이익·손실 모두)는 **사용자 본인의 책임**입니다.

## 라이선스

MIT
