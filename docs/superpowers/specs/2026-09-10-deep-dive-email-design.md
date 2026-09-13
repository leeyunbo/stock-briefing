# 아침 브리핑 이메일 전환 + 딥다이브 — 설계

**작성일**: 2026-09-10
**상태**: 설계 확정 (사용자 승인, 2026-09-09~10 대화)
**브랜치**: `feature/deep-dive-email`

## 배경

개인 아침 시장 브리핑(대시보드 + 5인 시선)은 `~/Project/morning-brief/` 러너가 평일 08:30에
Slack `#부자됩시당`으로 보낸다. 6/27 이후 53회 실행, 실패 0회로 안정적이다.

사용자가 뉴로퓨전 "월가소식"(ValleyAI 분석팀) 뉴스레터를 보고 두 가지를 원했다.

1. **깊이**: 주제 2~3개를 골라 "데이터 → 해석 → 결론 → 실행 아이디어 → 반론" 순서로 끝까지 파는 글.
   근거 숫자는 증권사 리포트급 1차 출처에서.
2. **형태**: 형광펜 헤더·문단·안내 박스가 있는 깔끔한 레이아웃. Slack mrkdwn으로는 불가능.

## 확정된 결정

| # | 결정 | 선택 | 기각한 대안 |
|---|---|---|---|
| 1 | 수신 경로 | **HTML 이메일** (Gmail SMTP, 레포에 발송기 있음) | WordPress+링크, Slack Block Kit |
| 2 | 재료 | **웹 리서치 강화 + 네이버 증권사 리포트 PDF 수집 동시** | 웹 리서치만 먼저 |
| 3 | Slack 브리핑과의 관계 | **이메일로 이전**. 상단 대시보드+5인 시선, 하단 딥다이브. Slack 발송 제거 | 별도 발행물, 링크만 |
| 4 | 딥다이브 주제 | **하루 2~3개, LLM 자동 선정**. 레이더·테마 연관 가산점 | 고정 축 3개, 하루 1개 |
| 5 | 리포트 수집 범위 | **시황·투자전략·산업·경제 당일 전체 + 종목분석은 레이더 종목만**. PDF 앞 3페이지만 | 전략·시황만, 전 카테고리 |
| 6 | 코드 위치 | **수집기·프롬프트·템플릿은 레포, 러너는 morning-brief** | 전부 morning-brief, 전부 레포 |
| 7 | 수신 주소 | `servers1@naver.com` | |

morning-brief의 "레포 무수정" 원칙은 **"saveticker 비공식 API 흔적만 레포 밖에"**로 좁힌다.

## 전체 흐름

```
morning-brief/brief.sh  (launchd, 화~토 08:30 KST — 변경 없음)
  → gate.py decide       (미국 세션 게이트 — 변경 없음)
  → run.py
      ├ [기존] scan_themes() ∥ gather_research()  → merge_saveticker()
      ├ [기존] build_market_overview()  → 대시보드 mrkdwn
      ├ [기존] gather_opinions()        → 5인 시선 mrkdwn
      ├ [신규] collect_reports()        → 증권사 리포트 발췌 목록
      ├ [신규] build_deep_dive()        → 주제 선정 + 주제별 본문
      ├ [신규] render_daily_brief()     → HTML
      └ [신규] send_email()             → servers1@naver.com
  → gate.py commit
```

수집 실패는 모두 **degrade**: 리포트 0건이면 웹 리서치만으로 딥다이브를 쓰고, 딥다이브 자체가
실패하면 대시보드+5인 시선만 담아 보낸다. 이메일 발송 실패만 러너 종료코드 1.

## 컴포넌트

### 1. `app/collector/naver_research.py` — 증권사 리포트 수집기

**입력**: 없음 (당일 날짜, `themes.WATCHLIST`).
**출력**: `list[ResearchReport]`

```python
@dataclass
class ResearchReport:
    category: str      # "시황" | "투자전략" | "산업" | "경제" | "종목"
    title: str
    broker: str        # 증권사
    date: date
    ticker: str | None # 종목분석만
    pdf_url: str | None
    read_url: str      # finance.naver.com/research/*_read.naver?nid=
    excerpt: str       # 본문 발췌 (PDF 앞 3p 또는 read 페이지 본문), 최대 6,000자
```

**소스** (모두 비인증, EUC-KR HTML):

| 카테고리 | 목록 URL | 필터 |
|---|---|---|
| 시황 | `finance.naver.com/research/market_info_list.naver` | 당일 |
| 투자전략 | `…/invest_list.naver` | 당일 |
| 산업 | `…/industry_list.naver` | 당일 |
| 경제 | `…/economy_list.naver` | 당일 |
| 종목 | `…/company_list.naver` | 당일 + 종목코드가 WATCHLIST(.KS/.KQ)에 있을 때만 |

목록 행 구조(2026-09-09 확인): 제목 `<a href="*_read.naver?nid=…">`, 증권사 `<td>`, PDF `<td class="file"><a href="https://stock.pstatic.net/stock-research/….pdf">` (없는 행 있음), 날짜 `<td class="date">26.09.09`. 종목분석은 첫 셀에 `/item/main.naver?code=012630`.

**본문 추출 규칙**
- PDF 있으면 `pypdf`로 **앞 3페이지** 텍스트. 없으면 read 페이지의 본문 영역 텍스트.
- 당일 = KST 기준 실행일. 08:30 실행 시 그날 아침 올라온 리포트가 대상(전날 리포트는 이미 지난 브리핑에 반영됐거나 시황으로 커버됨).
- 페이지네이션은 당일 행이 끊길 때까지만 (보통 1~2페이지).
- 카테고리별 상한 15건, 전체 상한 40건. 초과 시 조회수 순.
- 개별 리포트 실패는 로그 후 스킵. 목록 페이지 자체 실패는 해당 카테고리 빈 리스트.
- HTTP 클라이언트는 `app.core.http.get_http_client()` 재사용, 브라우저 UA 필수(기본 UA는 빈 응답).

**의존성 추가**: `pypdf` (requirements.txt).

### 2. `app/prompts/deep_dive.py` — 딥다이브 생성 (2단계)

**입력**: `overview: str`, `research: dict`(웹 리서치), `reports: list[ResearchReport]`, `run_id`
**출력**: `DeepDive`

```python
@dataclass
class DeepDiveTopic:
    headline: str    # 제목 목차용 짧은 문구 (예: "버블 경보가 풀린 코스피?")
    emoji: str       # 섹션 헤더 앵커 (🇰🇷 🇺🇸 🔬 등)
    body_html: str   # 문단형 본문. 허용 태그: <p> <strong> <em> <ul> <li>
    sources: list[str]  # "신한투자증권 Daily 신한생각 (9/9)" 형태

@dataclass
class DeepDive:
    summary: list[str]        # 전체 요약 불릿 2~3개
    topics: list[DeepDiveTopic]  # 2~3개
```

**1단계 — 주제 선정** (`select_topics`): 리포트 제목+발췌 요약 목록과 웹 리서치 거시·테마 요약을 주고
"중장기 투자자에게 오늘 가장 중요한 주제 2~3개"를 JSON으로 받는다. 각 주제에 근거 리포트 인덱스를
붙이게 한다. 선정 기준: (a) 1차 출처 숫자가 있는가, (b) 레이더·테마와 연관되는가(가산점),
(c) 하루짜리 등락이 아닌 흐름인가.

**2단계 — 본문 작성** (`write_topic`, 주제별 병렬): 해당 주제의 근거 리포트 발췌 전문 + 관련 웹 리서치를
주고 본문을 쓴다. 구조 강제:

1. 데이터 — 무슨 숫자가 나왔나 (출처 괄호)
2. 해석 — 그 숫자가 뜻하는 것
3. 결론 — 그래서 어떻게 봐야 하나 ("안전해졌다 ≠ 상승 베팅" 식의 한 줄)
4. 실행 아이디어 — 중장기 투자자가 할 수 있는 것 (있을 때만)
5. 반론 — 이 결론이 틀릴 수 있는 이유 한 가지

분량 주제당 400~700자. 말투는 기존 토스체(`opinions.TOSS_TONE` 재사용). 리포트에 없는 숫자 금지.
출력은 제한된 HTML 태그. `<script>` 등은 렌더 전에 화이트리스트 필터로 제거.

**프로바이더**: `get_provider(pipeline="morning_briefing", stage="deep_dive:select" | "deep_dive:write")`.
웹 검색은 이미 `gather_research`가 했으므로 여기서는 검색 없음.

### 3. `templates/email_daily_brief.html` + `app/publishing/email_template.py::render_daily_brief`

기존 `render_email`(티저)은 그대로 두고 함수 하나 추가.

**입력**: `date`, `topics_headline: str`("A / B / C"), `overview_html`, `opinions_html`, `deep_dive: DeepDive | None`
**레이아웃** (600px 카드, 기존 토스 팔레트 `#3182F6` 유지, 이메일 호환 위해 table + 인라인 스타일):

1. 로고 줄 (Moneydive)
2. **제목**: `{A} / {B} / {C} | 9월 10일 아침 브리핑` — 스크린샷처럼 제목이 목차
3. **안내 박스**: 회색 배경, "투자 권유 아님 · 개인 참고용" 2줄
4. **📝 전체 요약** (형광펜 헤더) — 딥다이브 summary 불릿
5. **📊 대시보드** — 기존 overview mrkdwn을 HTML로 변환 (`*굵게*`→`<strong>`, `===`→구분선, 🔺🔻 유지)
6. **💬 5명의 시선** — 페르소나별 소제목 + 문단
7. **주제별 딥다이브** — `{emoji} {headline}` 형광펜 헤더 + body_html + 출처 줄(작은 회색 글씨)
8. 푸터: 생성 시각, run_id

형광펜 헤더 = `<span style="background:#FFF3B0; padding:2px 6px; font-weight:700">`.
딥다이브가 None이면 4·7번 섹션 생략.

**mrkdwn → HTML 변환기** (`app/publishing/mrkdwn_html.py`): `*x*`→strong, `_x_`→em, `• `/`- ` 불릿→ul,
`===` 단독 줄→`<hr>`, 줄바꿈→`<br>`. 이것만. Slack 링크 문법 `<url|text>`는 현재 프롬프트에서 안 나오므로 미지원.

### 4. `~/Project/morning-brief/run.py` 변경 (로컬, git 없음)

- `collect_reports()` 호출을 `scan_themes`/`gather_research`와 함께 `asyncio.gather`.
- overview·opinions 생성 후 `build_deep_dive()` → `render_daily_brief()` → `send_email(to=MAIL_TO, …)`.
- `deliver_to_slack` 호출 제거. `config.sh`의 Slack 변수 2줄은 첫 이메일 정상 도착 확인 후 삭제.
- `--no-send`: HTML을 `morning-brief/preview.html`에 쓰고 경로 출력 (브라우저로 확인).
- `MAIL_TO` 는 `config.sh`에 `export BRIEF_MAIL_TO="servers1@naver.com"`.
- 로그 라인: `리포트 수집: N건 (시황 a, 전략 b, 산업 c, 경제 d, 종목 e)`, `딥다이브: 주제 k개`, `이메일 발송 완료: {to}`.

## 에러 처리 요약

| 실패 지점 | 동작 |
|---|---|
| 네이버 목록 페이지 | 해당 카테고리 빈 리스트, WARN |
| PDF 다운로드/파싱 | read 페이지 본문으로 폴백, 그것도 실패면 스킵 |
| 주제 선정 LLM | 딥다이브 None, 대시보드+5인만 발송, WARN |
| 주제 본문 LLM (일부) | 성공한 주제만 포함 |
| SMTP | 3회 재시도(기존) 후 실패 → rc=1, 게이트 commit 안 함 → 다음 날 재시도 |

## 테스트

- `tests/collector/test_naver_research.py`: 저장된 EUC-KR HTML 픽스처(시황 1페이지, 종목 1페이지)로 파싱 검증 — PDF 있는 행/없는 행, 날짜 필터, WATCHLIST 필터, 상한. PDF 추출은 3페이지짜리 소형 픽스처 PDF.
- `tests/prompts/test_deep_dive.py`: 프로바이더 목킹. 선정 JSON 파싱(2~3개 강제, 인덱스 범위), 본문 HTML 태그 화이트리스트, 일부 주제 실패 시 나머지 유지.
- `tests/publishing/test_mrkdwn_html.py`: 변환 규칙 표 기반.
- `tests/publishing/test_email_template.py`: 딥다이브 있음/없음 두 케이스 렌더, 제목 목차 문자열, 섹션 유무.
- 수동: `run.py --no-send`로 preview.html 생성 → 브라우저 확인 → 실제 발송 1회 → 네이버 메일 수신 확인 → Slack 제거.

## 범위 밖

- 증권사 리포트 원문 저장/아카이브 (DB 저장 안 함)
- 이메일 구독자 관리 (수신자 1명 고정)
- 웹 리서치 프롬프트 자체 수정 (딥다이브는 기존 결과를 재사용)
- Fear & Greed 418 오류 수정

---

## 개정 (2026-09-10 ~ 11)

### 형식 — '월가소식' 그대로 (사용자 피드백)
첫 발송분(대시보드 5섹션 + 5인 시선 + 딥다이브 3개, 렌더 높이 5,700px)에 "너무 주절주절, 다 때려박은 느낌" 피드백.
사용자 결정: **참고 이미지와 똑같이**. 그에 따라

- 대시보드·5인 시선 **제거**. 이메일 = 제목 목차 → 작성자·날짜 → 안내 박스 → 전체 요약(주제당 1줄) → 주제 3개.
- 주제 섹션 = 형광펜 헤더 `이모지 문장형 헤드라인 (주 출처)` + **문단 2개, 500자 안팎**, 담담한 "~습니다"체(용어 풀이 괄호 금지) + 자료 줄(최대 3건).
- 분량은 프롬프트만 믿지 않고 코드로 강제: 650자 초과 또는 3문단 이상이면 1회 압축 재작성, 실패 시 앞 2문단만.
- `DeepDiveTopic`에 `title`(목차용)·`headline`(헤더 문장)·`source`(주 출처) 분리. `render_daily_brief(brief_date, deep_dive, run_id)`.
- 러너는 `scan_themes`·`build_market_overview`·`gather_opinions`를 더 호출하지 않음(LLM 호출 7회 감소). `mrkdwn_html` 삭제.

### 수집기 — 네이버 API 전환
2026-09-10 `finance.naver.com/research/*`가 `stock.naver.com/research/daily`로 302 이전. HTML 파싱 폐기,
`m.stock.naver.com/api/research/{market|invest|industry|economy|company}?page&pageSize` (목록) +
`/api/research/{cat}/{researchId}` (상세: `content` 요약 HTML, `attachUrl` PDF)로 교체. 발췌 = 요약 텍스트 + PDF 앞 3페이지.

### 운영 관찰
- Claude CLI 사용 한도에 세 번 걸림(9/10 00:34, 08:30 정기 실행, 20:30). 08:30 정기 실행은 개요 생성 단계에서 실패해 **미발송**(rc=1, 게이트 미커밋 → 다음 날 재시도).
  딥다이브 호출엔 3회 백오프 재시도를 넣었고 개요·5인 호출은 제거됐지만, 한도 자체는 남은 리스크. API 프로바이더 폴백은 비용 결정이 필요해 미구현.
- 러너 `--report-date YYYY-MM-DD`로 미리보기 시 리포트 기준일을 바꿀 수 있음(새벽엔 당일 리포트가 0건).

### 2차 개정 (2026-09-12) — 거시 흐름 전용, 토스 리서치식
사용자: "토스 리서치처럼 이해하기 쉽게, 여자친구도 읽을 것. 너무 길면 안 됨. 종목 ㄴㄴ. 큰 흐름을 이해하고 투자 방향을 스스로 생각할 수 있는 수준."

- **주제 2개**, 거시 흐름만(금리·물가·환율·유가·경기·정책·수급·산업 사이클). 종목·목표주가 주제 금지, 관심 종목 가산점 삭제. 수집도 종목분석 제외(`MACRO_CATEGORIES`).
- 주제 구조 = 「무슨 일이에요?」「왜 중요해요?」「그래서요?」 각 2문장, 주제당 350자 안팎(450자 초과 시 압축). "~해요"체, 어려운 용어는 첫 등장 시 한 번 풀이. 매매 지시·종목 추천 금지, "그래서요?"는 판단 재료까지만.
- 전체 요약 → **"오늘 시장 한 줄"** 문장 하나.
- 템플릿: 소제목을 파란 라벨로 렌더(`DeepDiveTopic.sections`), 요약은 왼쪽 파란 줄 박스.
- 결과: 렌더 높이 1,534px(1차 5,772 → 2차 2,192 → 3차 1,534). 9/12 23:25 사용자에게 시험 발송.
- 수신자 2명(여자친구분)은 주소 받으면 `BRIEF_MAIL_TO`를 쉼표 목록으로 확장 예정 — 러너 `send_email` 호출을 수신자별로 반복.

### 3차 개정 (2026-09-13) — '시장 지도': 같은 변수를 매일 추적
사용자: "소제목으로 나누는 것보다 컴팩트하게. 거시적인 내용은 매일 똑같은 내용만 나올 것 같은데, 더 좋은 구성이 있을까?"

진단: 거시 서사는 몇 주 단위로 이어져서 "오늘 무슨 일" 형식이면 매일 같은 이야기에 숫자만 바뀐다. 거시를 이해한다는 건
같은 변수 몇 개를 계속 추적하는 것이므로, 형식이 그 추적을 도와야 한다. 소제목 3단은 틀이 내용보다 먼저 보여 제거.

**구성** (`app/prompts/market_map.py`, LLM 호출 1회 JSON)
1. `one_liner` — 오늘 시장 한 줄.
2. `threads` 2~4개 — 지금 시장을 움직이는 거시 서사. `id` 유지로 날짜가 바뀌어도 같은 줄기를 추적하고,
   `direction`은 어제 대비 강도(`up` 강해짐 / `flat` 그대로 / `down` 약해짐 / `new` 새 줄기). `since`로 등장일 보존.
   화면엔 화살표 + 한 줄 현황(70자)만.
3. `change` — 어제 줄기와 비교해 *정말 새로 생긴 것* 하나, 문단 2개(400자). 없으면 `null` → "새로 생긴 건 없어요".
4. `concept` — 오늘 용어 하나 3문장. `recent_concepts`(최근 10개)로 중복 회피. 덕분에 본문의 용어 풀이 괄호를 전부 제거.
5. `watch` — 이번 주 일정 2개.

**상태 보관**: 러너가 `~/Project/morning-brief/narratives.json`에 `{updated, threads[], recent_concepts[]}` 저장.
LLM이 줄기를 잘못 갱신해도 오래 어긋나지 않도록 **토요일(weekday==5)엔 `reset=True`**로 줄기를 처음부터 다시 잡는다.
러너 옵션: `--reset`(강제 재정비), `--no-state`(미리보기 반복 시 상태 미갱신).

**검증**: 1일차(9/11 리포트 40건) → 줄기 4개 모두 `new`. 2일차 시뮬레이션 → 3개가 id·since를 유지한 채
`flat/up/up`으로 갱신되고 1개 교체, 개념 이력에 `FOMC` 누적(중복 없음). 렌더 높이 1,301px.

**부수 수정**
- `naver_research.clean_text`: PDF 텍스트의 널 바이트(`\x00`)가 subprocess 인자로 못 넘어가 파이프라인 전체가 실패하던 문제.
- `summarizer.ClaudeCliProvider`: `stdin=subprocess.DEVNULL`. CLI가 stdin을 3초 기다린 뒤 경고와 함께 실패.
- `market_map._strip_fence`: `strip_code_block`이 마지막 HTML 태그 뒤를 잘라 JSON을 망가뜨려 자체 펜스 제거 사용.
