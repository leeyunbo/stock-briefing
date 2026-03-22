<p align="center">
  <strong>머니다이브</strong><br>
  AI가 매일 시장을 분석하고, 글을 쓰고, 발행까지 하는 자동화 금융 미디어
</p>

<p align="center">
  <a href="https://dailymoneydive.com">dailymoneydive.com</a>
</p>

---

## 서비스 소개

머니다이브는 **수집 → 분석 → 기사 작성 → 발행**까지 전 과정을 AI가 자동으로 수행하는 금융 콘텐츠 플랫폼이에요.

매일 15개 파이프라인이 자동 운영되며, 미국주식·한국주식·부동산·이슈·경제상식·SEO 기사를 WordPress 블로그에 발행하고 구독자에게 이메일로 전달합니다.

## 콘텐츠 라인업

| 콘텐츠 | 스케줄 | 설명 |
|--------|--------|------|
| **코스피 마감 브리핑** | 월~금 20:00 | 당일 코스피·코스닥 마감, 수급 동향, 주요 공시 정리 |
| **나스닥 마감 브리핑** | 화~토 08:00 | 전일 나스닥·S&P·다우 마감 요약, 주요 종목 등락 분석 |
| **이슈 딥다이브** | 매일 10·15·21시 | 가장 중요한 이슈 1개를 6개 섹션으로 깊게 분석하는 피처 기사 (LLM x2) |
| **주식 딥다이브** | 매일 11:00 | AI가 종목 1개를 선정해 증권사 리포트 수준의 심층 분석 (LLM x2) |
| **경제 상식** | 매일 07·11·17시 | 경제·투자 개념을 쉽게 풀어쓴 상식 콘텐츠 + FAQ 스키마 |
| **SEO 콘텐츠** | 매일 14:00 | 트렌드 키워드 기반 SEO 최적화 기사 자동 생성 + FAQ 스키마 |
| **부동산 브리핑** | 월 07:00 | 주간 부동산 뉴스 + 청약 일정 요약 |
| **AI 포트폴리오** | 화~토 08:30 | AI 기반 포트폴리오 관리 및 트래킹 |
| **암호화폐 트레이딩** | 15분/1시간 간격 | 규칙 기반 + AI 전략 자동 매매 |
| **데일리 다이제스트** | 매일 22:00 | 오늘 발행된 글 목록을 이메일 1통으로 정리 |

### 데이터 수집 파이프라인

| 파이프라인 | 스케줄 | 설명 |
|-----------|--------|------|
| **트렌드 키워드 수집** | 매일 07:00 | Google Trends·네이버 뉴스·Google Suggest에서 투자 관련 키워드 수집 |
| **GSC 기회 키워드** | 월 06:00 | Google Search Console 데이터 분석, 높은 노출·낮은 CTR 키워드 발굴 |

## 아키텍처

![시스템 아키텍처](docs/architecture.drawio.png)

상세 설명은 **[docs/architecture.md](docs/architecture.md)** 참고.

## 기술 스택

| 분류 | 기술 |
|------|------|
| Runtime | Python 3.13, FastAPI, APScheduler |
| AI | Claude API, Gemini (생성 + 임베딩) |
| 데이터 수집 (KR) | 네이버 금융, 네이버 뉴스, DART, 청약홈, pykrx |
| 데이터 수집 (US) | Finnhub, yfinance, SEC EDGAR |
| 데이터 수집 (SEO) | Google Search Console API, Google Trends, Google Suggest |
| 암호화폐 | Upbit API (pyupbit), pandas-ta |
| 중복 제거 | ChromaDB + Gemini 시맨틱 임베딩 |
| 발행 | WordPress REST API, Gmail SMTP, Google Indexing API |
| SEO | Rank Math 자동 설정, FAQ JSON-LD 스키마, OG 이미지 생성, Unsplash 이미지, 내부 링크 자동화 |
| 차트 | Matplotlib (주가 차트 + 기술적 분석 차트) |
| DB | SQLite + SQLAlchemy (async) |
| 인프라 | Oracle Cloud (ARM), systemd |

## 프로젝트 구조

```
app/
├── core/                          # 설정, DB, 모델
│   ├── config.py                  #   환경 변수 및 설정
│   ├── database.py                #   SQLite + SQLAlchemy async
│   ├── http.py                    #   HTTP 클라이언트
│   ├── logging_config.py          #   로깅 설정
│   └── models.py                  #   SQLAlchemy ORM 모델 (12개)
├── collector/                     # 데이터 수집 모듈
│   ├── market.py                  #   네이버 금융 (코스피/코스닥 지수)
│   ├── nasdaq.py                  #   Finnhub (나스닥/S&P/다우 + 관심 종목)
│   ├── market_scan.py             #   나스닥 100 스캔 + 매크로 지표 (VIX, 국채, DXY)
│   ├── news.py                    #   네이버 뉴스 검색 API
│   ├── dart.py                    #   DART 공시
│   ├── real_estate.py             #   청약홈 + 부동산 뉴스
│   ├── stock_research.py          #   US 종목 딥리서치 (Finnhub + yfinance + SEC)
│   ├── kr_stock_research.py       #   KR 종목 딥리서치 (네이버 금융 API)
│   ├── crypto.py                  #   암호화폐 데이터 (Upbit)
│   ├── technical.py               #   기술적 분석 지표
│   ├── trends.py                  #   트렌드 키워드 수집 (Google Trends, 네이버, Google Suggest)
│   ├── gsc.py                     #   Google Search Console API + 기회 키워드
│   ├── dedup.py                   #   ChromaDB + Gemini 시맨틱 중복 제거
│   └── snapshot.py                #   지수 스냅샷 DB 저장/조회
├── prompts/                       # LLM 프롬프트 + 호출
│   ├── nasdaq.py                  #   나스닥 브리핑
│   ├── news_dive.py               #   뉴스 딥다이브
│   ├── issue_dive.py              #   이슈 딥다이브 (LLM x2)
│   ├── deep_research.py           #   US 종목 딥리서치
│   ├── stock_deep_dive.py         #   주식 딥다이브 (자동 종목 선정 + 기사 생성)
│   ├── real_estate.py             #   부동산 브리핑
│   ├── economy_content.py         #   경제 상식 콘텐츠 (FAQ 포함)
│   ├── seo_content.py             #   SEO 콘텐츠 (패턴 기반 + FAQ)
│   ├── chart_analysis.py          #   차트 패턴 분석
│   ├── portfolio.py               #   포트폴리오 의사결정
│   └── crypto_trading.py          #   암호화폐 트레이딩 전략
├── pipeline/                      # 파이프라인 오케스트레이션
│   ├── base.py                    #   공통 스텝 러너 + Publisher 패턴
│   ├── kospi.py                   #   코스피 브리핑
│   ├── nasdaq.py                  #   나스닥 브리핑
│   ├── issue_dive.py              #   이슈 딥다이브
│   ├── stock_deep_dive.py         #   주식 딥다이브
│   ├── economy_content.py         #   경제 상식 (하루 3회)
│   ├── seo_content.py             #   SEO 콘텐츠 자동 생성
│   ├── real_estate.py             #   부동산 브리핑
│   ├── portfolio.py               #   AI 포트폴리오
│   ├── chart_analysis.py          #   차트 분석
│   ├── crypto_trading.py          #   암호화폐 트레이딩
│   ├── digest.py                  #   데일리 다이제스트
│   ├── trend_collect.py           #   트렌드 키워드 수집
│   └── gsc_collect.py             #   GSC 데이터 + 기회 키워드 발굴
├── publishing/                    # 발행 모듈
│   ├── wordpress.py               #   WordPress REST API 발행
│   ├── email_sender.py            #   이메일 발송 (Gmail SMTP)
│   ├── email_template.py          #   이메일 HTML 템플릿
│   ├── og_image.py                #   OG 이미지 생성 (Pillow, 카테고리별 그라데이션)
│   ├── chart.py                   #   주가 차트 렌더링 (Matplotlib)
│   ├── ta_chart.py                #   기술적 분석 차트
│   ├── unsplash.py                #   Unsplash 이미지 검색
│   └── google_indexing.py         #   Google 색인 요청
├── seo/                           # SEO 인프라
│   ├── topic_queue.py             #   SEO 토픽 큐 (테마 관련·테마 리더)
│   ├── economy_queue.py           #   경제 상식 토픽 큐 (3가지 패턴)
│   ├── faq_schema.py              #   FAQ 추출 + JSON-LD 마크업
│   ├── internal_links.py          #   내부 링크 자동 삽입
│   └── wp_dedup.py                #   WordPress 중복 콘텐츠 탐지
├── trading/                       # 암호화폐 트레이딩
│   ├── upbit_client.py            #   Upbit API 클라이언트
│   ├── indicators.py              #   기술적 지표
│   ├── signals.py                 #   매매 시그널
│   └── models.py                  #   트레이딩 모델
├── routes/                        # FastAPI 라우트
│   ├── dashboard.py               #   대시보드 (56일 파이프라인 캘린더 + 트렌드 히트맵)
│   ├── archive.py                 #   기사 아카이브
│   ├── pipelines.py               #   수동 파이프라인 실행 UI
│   ├── crypto.py                  #   암호화폐 트레이딩 대시보드
│   ├── subscribe.py               #   이메일 구독 관리
│   └── traces.py                  #   AI 호출 트레이싱 브라우저
├── summarizer.py                  # AI 프로바이더 (Claude/Gemini) + SEO 메타 추출
├── scheduler.py                   # APScheduler 크론 스케줄 설정
└── tracing.py                     # AI 호출 트레이싱 → /traces 대시보드
```

## 대시보드

관리용 웹 대시보드를 제공합니다.

| 경로 | 설명 |
|------|------|
| `/dashboard` | 56일 파이프라인 실행 캘린더 + 트렌드 키워드 히트맵 |
| `/archive` | 발행된 기사 목록 |
| `/pipelines` | 수동 파이프라인 실행 UI |
| `/crypto` | 암호화폐 트레이딩 대시보드 |
| `/traces` | AI 호출 트레이싱 브라우저 (파이프라인 디버깅) |
| `/subscribe` | 이메일 구독 관리 |

## 실행

```bash
# 서버 시작 (스케줄러 포함)
./run.sh start

# 개별 파이프라인 수동 실행
python run_html_only.py              # 전체 파이프라인 HTML 생성
python -m app.research               # 딥리서치 실행
python -m app.research --ticker NVDA  # 특정 종목 딥리서치
```

## 발행 프로세스

1. **DB 저장** — 브리핑 결과를 SQLite에 저장 (같은 날 재실행 시 upsert)
2. **OG 이미지** — Pillow로 카테고리별 그라데이션 + 장식 요소 이미지 생성 → WordPress 업로드
3. **Unsplash** — LLM이 추출한 `image_keyword`로 관련 사진 검색 → 본문 상단 삽입
4. **FAQ 스키마** — 본문에서 Q/A 패턴 추출 → JSON-LD 마크업 자동 삽입
5. **내부 링크** — 기존 발행 콘텐츠와 자동 내부 링크 연결
6. **WordPress** — REST API로 포스트 발행, Rank Math SEO 메타 자동 설정
7. **Google 색인** — 발행 즉시 Google Indexing API로 색인 요청
8. **이메일** — 활성 구독자에게 브리핑 이메일 발송
