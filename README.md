# Swing Scanner

한국(코스피200)·미국(S&P500) 약 700종목을 매일 자동 스캔해  
**쌍바닥·골든크로스·박스권 돌파·눌림목** 4가지 패턴을 탐지하고,  
신뢰도 점수와 진입/손절/목표가를 제시하는 스윙매매 차트 발굴 시스템입니다.  
주봉(추세) → 일봉(패턴) → 4시간봉(타이밍)의 멀티 타임프레임으로 가짜 신호를 걸러냅니다.

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

```bash
sqlite3 data/scanner.db ".tables"
# backtest_results  fundamentals     ohlcv_intraday    scan_results
# ohlcv_daily       ohlcv_weekly     universe
```

## 일일 사용 흐름

### 1단계 — 전체 스캔 (KR + US)

```bash
scanner scan
```

내부적으로 다음 순서로 실행됩니다.

1. 유니버스 확인 (7일 이상 미갱신 시 자동 갱신)
2. OHLCV + 재무 데이터 fetch (`pykrx` / `yfinance`)
3. 패턴 탐지 — ThreadPool 병렬 처리 (진행률 표시)
4. DB 저장
5. TOP 10 결과 출력

완료 후 신뢰도 70점 이상 종목 최대 10개가 컬러 테이블로 출력됩니다.

### 2단계 — 결과 조회

```bash
# 오늘 스캔 결과 전체
scanner results

# 특정 날짜
scanner results --date 2026-05-04

# 패턴 필터
scanner results --pattern pullback

# 최소 점수 필터
scanner results --min-confidence 80
```

### 3단계 — 종목 상세 보기

```bash
scanner show AAPL
scanner show 005930 --date 2026-05-04
```

패턴 세부 정보(진입가·손절가·목표가·리스크비율·주봉 추세)를 패널로 출력합니다.

---

## 명령어 레퍼런스

### `scanner scan`

전체 파이프라인을 실행합니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--market`, `-m` | `all` | 스캔 시장: `kr` \| `us` \| `all` |
| `--pattern`, `-p` | _(없음)_ | 패턴 필터 (쉼표 구분, 예: `pullback,box_breakout`) |
| `--min-confidence` | `75.0` | 상위 결과 표시 최소 신뢰도 (0~100) |
| `--no-volume-filter` | `False` | 거래량 필터 비활성화 |
| `--with-fundamental-filter` | `False` | 재무 필터 활성화 |
| `--skip-fetch` | `False` | 데이터 fetch 생략 (DB 기존 데이터로 스캔) |

```bash
# 한국 시장만, 눌림목 패턴만, 재무 필터 포함
scanner scan --market kr --pattern pullback --with-fundamental-filter

# fetch 없이 기존 DB 데이터로 빠르게 재스캔
scanner scan --skip-fetch --min-confidence 60
```

**Ctrl+C 처리:** fetch 단계에서 중단하면 저장 없이 종료합니다. 패턴 탐지 중 중단하면 완료된 종목까지 부분 저장합니다.

---

### `scanner results`

저장된 스캔 결과를 조회합니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--date`, `-d` | 오늘 | 조회 기준일 (YYYY-MM-DD) |
| `--pattern` | _(없음)_ | 패턴 이름 필터 |
| `--min-confidence` | `0.0` | 최소 신뢰도 필터 |
| `--limit` | `50` | 최대 출력 행 수 |

```bash
scanner results --date 2026-05-01 --pattern golden_cross --min-confidence 75
```

---

### `scanner show <TICKER>`

특정 종목의 최신(또는 지정일) 스캔 결과를 상세 출력합니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--date`, `-d` | 오늘 | 조회 기준일 (YYYY-MM-DD) |

```bash
scanner show TSLA
scanner show 035720 --date 2026-05-02
```

---

### `scanner version`

패키지 버전을 출력합니다.

```bash
scanner version
# swing-scanner 0.1.0
```

---

### `scanner backtest`

과거 스캔 결과를 재생해 패턴 성과를 측정합니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--pattern`, `-p` | _(필수)_ | 패턴 이름 |
| `--period` | `90` | 백테스트 기간 (일) |
| `--hold` | `10` | 최대 보유 일수 |
| `--min-score` | `70.0` | 최소 신뢰도 점수 |

```bash
scanner backtest --pattern double_bottom --period 90 --hold 10
scanner backtest --pattern golden_cross  --period 180 --min-score 80
```

---

### `scanner serve`

FastAPI 대시보드 서버를 시작합니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 바인드 호스트 |
| `--port`, `-p` | `8000` | 포트 번호 |
| `--reload` | `False` | 코드 변경 시 자동 재시작 |
| `--open/--no-open` | `True` | 브라우저 자동 열기 |

```bash
scanner serve
# http://127.0.0.1:8000      — 대시보드
# http://127.0.0.1:8000/docs — Swagger API 문서
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 서버 상태 |
| GET | `/api/markets/summary` | 일일 시장 요약 |
| GET | `/api/scan-results` | 스캔 결과 목록 (필터·정렬) |
| GET | `/api/stocks/{ticker}/ohlcv` | OHLCV + 이동평균 (차트용) |
| GET | `/api/stocks/{ticker}/analysis` | 분석 결과 + AI 코멘트 |
| GET | `/api/patterns` | 패턴 목록 및 오늘 탐지 수 |
| GET | `/api/patterns/{name}/stats` | 패턴별 통계 |
| POST | `/api/backtest/run` | 백테스트 실행 |

---

## Windows 자동화

매일 오전 7시에 자동으로 스캔을 실행하려면:

```powershell
# 관리자 PowerShell에서 실행
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1

# 실행 시각 변경 (기본: 07:00)
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1 -Time "06:30"
```

로그는 `logs/daily_scan.log` 에 저장됩니다.  
수동 실행: `scripts\start_dashboard.bat` 더블클릭.

---

## 패턴 이름 목록

| 이름 | 설명 |
| --- | --- |
| `double_bottom` | 쌍바닥 |
| `golden_cross` | 골든크로스 |
| `box_breakout` | 박스권 돌파 |
| `pullback` | 눌림목 (주봉 상승 추세 필수) |

---

## 트러블슈팅

### `scanner` 명령을 찾을 수 없다

```
'scanner' is not recognized as an internal or external command
```

**원인:** `pip install -e .` 를 하지 않았거나, 가상환경이 활성화되지 않았습니다.

```bash
# 가상환경 활성화 후 재설치
.\.venv\Scripts\Activate.ps1
pip install -e .
```

---

### 한글이 깨진다 (UnicodeEncodeError)

Windows 콘솔 기본 인코딩이 cp949일 때 발생합니다.

```bash
# PowerShell / cmd 세션에 적용
chcp 65001
$env:PYTHONIOENCODING = "utf-8"
scanner scan
```

또는 `.env` 파일에 `PYTHONIOENCODING=utf-8` 을 추가하세요.

---

### `활성 종목이 없습니다` 경고와 함께 종료

Universe 테이블이 비어 있습니다. 유니버스를 수동으로 갱신하세요.

```bash
python -c "from scanner.kr.universe import update_kospi200; from scanner.us.universe import update_sp500; update_kospi200(); update_sp500()"
```

또는 `--skip-fetch` 없이 `scanner scan` 을 실행하면 자동으로 갱신됩니다.

---

### `pykrx` 빈 데이터 반환

KRX 서버는 휴장일·장중 호출 시 빈 DataFrame을 반환합니다. 장 마감(오후 4시) 이후 실행을 권장합니다. 빈 데이터 종목은 자동으로 스캔에서 제외됩니다.

---

### DB가 손상되거나 초기화가 필요할 때

```bash
# DB 파일 삭제 후 재초기화 (기존 데이터 모두 삭제됨)
Remove-Item data\scanner.db
python -m scanner.db.migrations
```

---

### 테스트 실행

```bash
python -m pytest tests/ -v
```

특정 모듈만:

```bash
python -m pytest tests/test_cli.py -v
python -m pytest tests/test_scoring.py -v
```

---

## 폴더 구조

```
scanner/
  config.py          # 임계값·가중치·필터 상수
  cli.py             # typer CLI 진입점
  pipeline.py        # 일일 파이프라인 오케스트레이터
  scanner.py         # analyze_ticker / scan_universe
  db/                # SQLAlchemy 모델·세션·마이그레이션·저장소
  data/              # pykrx/yfinance 어댑터·유니버스 빌더
  indicators/        # MA, RSI, 볼린저 등 기술 지표
  patterns/          # 4가지 패턴 탐지기
  scoring/           # 신뢰도 점수 엔진
  filtering/         # 거래량·재무 필터
data/                # SQLite DB · 캐시 (gitignore)
logs/                # 로그 파일 (gitignore)
tests/               # pytest (단위 + 통합)
  fixtures/          # 테스트 픽스처 CSV
```

## 개발 규칙

- 커밋 메시지: **Conventional Commits** (`feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`)
- 브랜치: `feat/step-N-이름`, `fix/이슈요약`
- 한 STEP = 5~15개 의미 단위 커밋 → PR → squash 머지 → 태그 (`step-N-complete`)
- 코드 스타일: 타입 힌트 필수, 한국어 docstring, 영어 식별자
- 자세한 규칙은 [`CLAUDE.md`](./CLAUDE.md) 참조

## 면책 조항

본 시스템은 **개인 투자자의 학습·연구·차트 발굴 보조** 목적으로 제작되었으며, 어떠한 매매 권유나 수익 보장도 하지 않습니다.

출력되는 점수·진입가·손절가·목표가는 **과거 데이터 기반의 통계적 추정**이며, 실제 매매 결과를 보장하지 않습니다.

모든 매매 의사결정과 그 결과는 **사용자 본인의 책임**입니다.

## 라이선스

MIT
