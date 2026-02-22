# Stock Briefing

매일 아침 7시, AI가 전일 시장 데이터/공시/뉴스를 수집하고 요약해서 이메일로 발송하는 뉴스레터 서비스에요.
- 현재는 국장 브리핑만 제공해요.

## 주요 기능

- **시장 데이터 수집** — 코스피/코스닥 지수, 시총 TOP10, 투자자별 매매동향 (네이버 금융 API)
- **공시 수집 + 필터링** — DART OpenAPI에서 전일 공시 수집, 개인투자자 관련 키워드 자동 필터링
- **뉴스 수집** — 네이버 뉴스 RSS, 등락률 상위 종목별 뉴스 추가 수집
- **AI 브리핑 생성** — Claude / Gemini로 친근한 톤의 HTML 브리핑 요약
- **이메일 발송** — 구독자에게 다크 테마 이메일 자동 발송
- **휴장일 감지** — 시장 데이터 날짜 기반 자동 판단, 뉴스만 발송
- **구독 관리** — 웹 페이지에서 이메일 구독/해지
- **아카이브** — 과거 브리핑 조회 (페이지네이션)

## 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| HTTP 클라이언트 | httpx (비동기) |
| AI | Anthropic Claude API(메인), Google Gemini API(테스트 용) |
| 스케줄링 | APScheduler |
| 이메일 | aiosmtplib + Gmail SMTP |
| 템플릿 | Jinja2 |
| 테스트 | pytest + pytest-asyncio |

## 프로젝트 구조

```
stock-briefing/
├── main.py                  # FastAPI 앱 진입점
├── run.sh                   # 서버 시작/종료 스크립트
├── app/
│   ├── config.py            # 환경변수 설정 (pydantic-settings)
│   ├── database.py          # SQLAlchemy 비동기 세션
│   ├── models.py            # Briefing, Subscriber 모델
│   ├── pipeline.py          # 파이프라인 오케스트레이터
│   ├── summarizer.py        # AI 프로바이더 + 프롬프트 구성
│   ├── scheduler.py         # APScheduler 설정
│   ├── email_sender.py      # 이메일 발송 (tenacity 재시도)
│   ├── email_template.py    # 이메일 HTML 렌더링
│   ├── routes/              # FastAPI 라우터 (구독, 아카이브)
│   └── collector/
│       ├── market.py        # 네이버 금융 API
│       ├── dart.py          # DART 공시 API
│       └── news.py          # 네이버 뉴스 RSS
├── templates/               # Jinja2 템플릿 (이메일, 웹 페이지)
└── tests/                   # pytest 테스트 (36개)
```

## 파이프라인 흐름

```
수집 (collect_data)
├── 네이버 금융 → 시장 데이터
├── DART → 공시 → 키워드 필터링
├── 네이버 뉴스 → 일반 뉴스
└── 등락률 상위 종목 → 종목별 뉴스
        ↓
요약 (summarize)
└── AI가 수집 데이터를 HTML 브리핑으로 변환
        ↓
저장 (save_briefing)
└── SQLite DB에 저장 (같은 날 재실행 시 업데이트)
        ↓
발송 (send_emails)
└── 구독자에게 이메일 발송 (재시도 포함)
``` 
