# 파이프라인

## 공통 처리 흐름

모든 파이프라인은 동일한 패턴을 따른다.

```
COLLECT ──→ DEDUP ──→ SUMMARIZE (LLM) ──→ PUBLISH
```

| 단계 | 설명 | 핵심 기술 |
|------|------|-----------|
| **Collect** | 외부 API에서 시장 데이터·뉴스·공시 수집 | Finnhub, yfinance, 네이버 금융/뉴스, DART, SEC EDGAR |
| **Dedup** | 시맨틱 임베딩으로 중복 뉴스 제거 (유사도 0.9 이상) | ChromaDB + Gemini Embedding |
| **Summarize** | AI가 수집 데이터 기반으로 기사 생성 + SEO 메타 추출 | Claude API / CLI |
| **Publish** | DB 저장 → OG 이미지 → WordPress 발행 → 이메일 → 색인 | WordPress REST API, Gmail SMTP, Google Indexing API |

---

## 이슈 딥다이브 — 2단계 LLM 프로세스

일반 파이프라인과 달리 **LLM을 2번** 호출하는 심층 분석 파이프라인.

```
Collect → Dedup → LLM #1 (이슈 선정) → Research → LLM #2 (기사 생성) → Publish
```

| 단계 | 설명 |
|------|------|
| **Collect** | `scan_market()` + `fetch_macro_indicators()` 재활용 |
| **Dedup** | 별도 컬렉션 `issue_dive_news`로 ChromaDB dedup |
| **LLM #1** | 전체 뉴스 중 가장 중요한 이슈 1개 선정 (JSON 응답) |
| **Research** | 선정 이슈의 키워드로 네이버 뉴스 추가 수집 + 관련 종목 스크리닝 |
| **LLM #2** | 심층 자료 기반 6개 섹션 피처 기사 생성 (4000~5000단어) |
| **Publish** | DB + WordPress + 이메일 (공통 스텝 재활용) |

### 중복 주제 방지

- **아티클 레벨** — ChromaDB 시맨틱 임베딩으로 같은 기사 필터링
- **토픽 레벨** — 최근 7일 발행 제목을 LLM 프롬프트에 전달, 같은 각도 반복 방지
- 단, 상황이 급변한 경우 (정책 전환, 급락→급등 반전 등)는 재선정 허용

### 기사 섹션 구성

1. 무슨 일이 일어났나 (팩트 타임라인)
2. 배경과 맥락 (왜 이런 일이 일어났나)
3. 시장 임팩트 분석 (수혜주/피해주 테이블 포함)
4. 역사적 유사 사례
5. 시나리오 분석 (Bull/Base/Bear)
6. 결론 — 앞으로 지켜볼 포인트

---

## 주식 딥다이브 — 2단계 LLM 프로세스

이슈 딥다이브와 유사하게 **LLM을 2번** 호출하는 종목 분석 파이프라인.
수동(티커 지정) + 자동(AI 선정) 두 모드를 지원하며, KR/US 시장 모두 대응.

```
[자동 모드] Collect Market Context → LLM #1 (종목 선정)
                                          ↓
[수동 모드] ticker 입력 ──────────→ detect_market (KR/US)
                                          ↓
                              KR: fetch_kr_stock_research (네이버 금융)
                              US: fetch_stock_research (Finnhub + yfinance)
                                          ↓
                              LLM #2 (종목 분석 기사 생성) → Publish
```

| 단계 | 설명 |
|------|------|
| **LLM #1** (자동 모드) | 시장 스캔 데이터로 딥다이브할 종목 1개 선정 (JSON: ticker, market, why_picked) |
| **detect_market** | 티커를 분석해 KR/US 시장 판별 (`삼성전자` → KR, `NVDA` → US) |
| **Collect** | KR: 네이버 금융 API (기업정보, 재무제표, 시세, 1년 주가) / US: Finnhub + yfinance + SEC EDGAR |
| **LLM #2** | 골드만삭스/모건스탠리급 애널리스트 스타일 심층 분석 리포트 생성 |
| **Publish** | DB + WordPress + 이메일 (공통 스텝 재활용) |

### 기사 섹션 구성

1. 투자 요약 (한 줄 판단 + 목표주가 + 핵심 포인트 3개)
2. 사업 분석 (매출 구성, 경쟁 우위, peer 비교)
3. 재무 분석 (4분기 트렌드, 마진, FCF, peer 비교)
4. 밸류에이션 (PER/PBR/PS, 목표주가 산출 근거)
5. 호재와 악재 (구체적 이벤트 + 종합 판단)
6. 리스크 요인 (발생 가능성 + 임팩트 평가)
7. 결론 (Bull/Base/Bear 시나리오 + 최종 판단)

---

## 트레이싱 (Observability)

모든 AI 호출은 `TracingProvider`가 자동으로 감싸서 기록한다.

- **기록 항목** — latency_ms, input/output tokens, 성공/실패, 에러 메시지
- **그룹핑** — `run_id`로 파이프라인 실행 단위 추적
- **저장** — `ai_traces` 테이블 (SQLite, 동기 저장)
- **열람** — `/traces` 웹 대시보드에서 run별 실행 이력 확인

저장 실패해도 파이프라인은 멈추지 않는다 (fail-safe).
