# Stock Briefing

매일 아침, AI가 시장 데이터/공시/뉴스를 수집하고 요약해서 이메일로 발송하는 뉴스레터 서비스에요.

3개 파이프라인이 자동 운영됩니다:
- **🇰🇷 한국 시장 브리핑** — 화~토 오전 7시 (전일 코스피/코스닥)
- **🇺🇸 나스닥 마감 브리핑** — 월~금 오전 8시 (나스닥 장마감 직후)
- **💡 투자 아이디어 리서치** — 월~금 오전 9시 (테마 발굴 + 숨겨진 종목 분석)

## 주요 기능

### 한국 시장 브리핑
- **시장 데이터 수집** — 코스피/코스닥 지수, 시총 TOP10, 투자자별 매매동향 (네이버 금융 API)
- **공시 수집 + 필터링** — DART OpenAPI에서 전일 공시 수집, 개인투자자 관련 키워드 자동 필터링
- **뉴스 수집** — 네이버 뉴스 RSS, 등락률 상위 종목별 뉴스 추가 수집
- **휴장일 감지** — 시장 데이터 날짜 기반 자동 판단, 뉴스만 발송

### 나스닥 마감 브리핑
- **나스닥 시장 데이터** — Finnhub API로 주요 지수(나스닥, S&P500, 다우) + 주요 종목 시세 수집
- **미국 시장 뉴스** — Finnhub 뉴스 API로 주요 시장 뉴스 수집

### 투자 아이디어 리서치
- **3단계 테마 발굴 퍼널** — 시장 스캔 → Claude 테마 분석 → 후보 종목 스크리닝 → 종합 리포트
- **나스닥 100 스캔** — yfinance로 나스닥 100 종목 일괄 시세 수집 + Finnhub 뉴스/실적 캘린더
- **Claude 테마 선정** — 뉴스·실적에서 투자 테마 도출, 직접 수혜주 + 숨겨진 종목 추천
- **재무 스크리닝** — 추천 종목의 프로필·밸류에이션·애널리스트 추천 자동 수집
- **개별 종목 딥리서치** — 특정 종목 지정 시 Finnhub + yfinance + SEC EDGAR 종합 분석

### 공통
- **AI 브리핑 생성** — Claude CLI(`claude -p`)로 친근한 톤의 HTML 브리핑 요약
- **이메일 발송** — 구독자에게 다크 테마 이메일 자동 발송
- **구독 관리** — 웹 페이지에서 이메일 구독/해지
- **아카이브** — 과거 브리핑 조회 (페이지네이션)

## 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| HTTP 클라이언트 | httpx (비동기) |
| AI | Claude CLI (`claude -p`), Anthropic Claude API, Google Gemini API |
| 데이터 (미국) | Finnhub API, yfinance, SEC EDGAR |
| 스케줄링 | APScheduler |
| 이메일 | aiosmtplib + Gmail SMTP |
| 템플릿 | Jinja2 |
| 테스트 | pytest + pytest-asyncio |

## 프로젝트 구조

```
stock-briefing/
├── main.py                  # FastAPI 앱 진입점
├── run.sh                   # 서버 시작/종료/재시작 스크립트
├── app/
│   ├── config.py            # 환경변수 설정 (pydantic-settings)
│   ├── database.py          # SQLAlchemy 비동기 세션
│   ├── models.py            # Briefing, Subscriber 모델
│   ├── pipeline.py          # 한국 시장 파이프라인 오케스트레이터
│   ├── nasdaq_pipeline.py   # 나스닥 마감 브리핑 파이프라인
│   ├── research_pipeline.py # 투자 아이디어 리서치 파이프라인
│   ├── research.py          # 리서치 CLI 엔트리포인트
│   ├── summarizer.py        # AI 프로바이더 (Claude API, Claude CLI, Gemini)
│   ├── scheduler.py         # APScheduler 설정 (3개 파이프라인)
│   ├── email_sender.py      # 이메일 발송 (tenacity 재시도)
│   ├── email_template.py    # 이메일 HTML 렌더링 (다크 테마)
│   ├── routes/              # FastAPI 라우터 (구독, 아카이브)
│   └── collector/
│       ├── market.py        # 네이버 금융 API (한국 시장)
│       ├── dart.py          # DART 공시 API
│       ├── news.py          # 네이버 뉴스 RSS
│       ├── finnhub_client.py # Finnhub API 클라이언트 (나스닥)
│       └── stock_research.py # 종합 리서치 데이터 수집기
├── templates/               # Jinja2 템플릿 (이메일, 웹 페이지)
└── tests/                   # pytest 테스트
```

## 파이프라인 흐름

### 한국 시장 브리핑 (화~토 07:00)

```
수집 (collect_data)
├── 네이버 금융 → 시장 데이터
├── DART → 공시 → 키워드 필터링
├── 네이버 뉴스 → 일반 뉴스
└── 등락률 상위 종목 → 종목별 뉴스
        ↓
요약 → 저장 → 발송
```

### 나스닥 마감 브리핑 (월~금 08:00)

```
수집 (Finnhub API)
├── 주요 지수 시세 (나스닥, S&P500, 다우 등)
├── 주요 종목 시세 (AAPL, MSFT, NVDA 등)
└── 시장 뉴스
        ↓
요약 (claude -p) → 저장 → 발송
```

### 투자 아이디어 리서치 (월~금 09:00)

```
Stage 1 — 시장 스캔
├── yfinance → 나스닥 100 일괄 시세
├── Finnhub → 시장 뉴스
└── Finnhub → 실적 캘린더
        ↓
Stage 2 — 테마 분석 (claude -p)
└── Claude가 뉴스·데이터에서 투자 테마 도출
    ├── 직접 수혜주 추천
    └── 숨겨진 종목 발굴
        ↓
Stage 3 — 후보 스크리닝 + 리포트
├── Finnhub → 추천 종목 프로필·밸류에이션·애널리스트
└── Claude → 5섹션 종합 리포트 작성
        ↓
저장 → 발송
```

## CLI 사용법

```bash
# 서버 관리
./run.sh start          # 서버 시작 (스케줄러 포함)
./run.sh stop           # 서버 종료
./run.sh restart        # 서버 재시작
./run.sh status         # 서버 상태 확인
./run.sh log            # 로그 실시간 확인

# 투자 아이디어 리서치 수동 실행
python -m app.research                          # 테마 발굴 → 전체 구독자 발송
python -m app.research --email user@example.com  # 특정 주소로만 발송
python -m app.research --no-email                # 발송 없이 생성만

# 개별 종목 딥리서치
python -m app.research --ticker NVDA              # NVDA 심화 분석 → 전체 발송
python -m app.research --ticker AAPL --no-email   # AAPL 분석, 발송 안 함
```
