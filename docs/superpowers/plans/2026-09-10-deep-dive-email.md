# 아침 브리핑 이메일 전환 + 딥다이브 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평일 아침 Slack 브리핑을 "대시보드 + 5인 시선 + 증권사 리포트 기반 딥다이브 2~3개"를 담은 HTML 이메일로 바꾼다.

**Architecture:** 레포에 수집기(`naver_research`)·프롬프트(`deep_dive`)·렌더러(`mrkdwn_html`, `render_daily_brief`)를 추가하고, git 밖의 `~/Project/morning-brief/run.py`가 이들을 import해 엮어 Gmail SMTP로 보낸다. 모든 신규 단계는 실패 시 축소 발송(degrade)한다.

**Tech Stack:** Python 3.13, httpx(AsyncClient 공유), BeautifulSoup4(html.parser), pypdf, jinja2, Claude CLI 프로바이더(`get_provider`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-10-deep-dive-email-design.md`

## Global Constraints

- 네이버 리서치 페이지는 EUC-KR. `resp.content.decode("euc-kr", errors="ignore")`로 읽는다. 브라우저 UA 필수.
- 리포트 수집 상한: 카테고리별 15건, 전체 40건, 초과 시 조회수 내림차순.
- PDF는 앞 3페이지만, 발췌 최대 6,000자.
- 딥다이브 주제 2~3개, 주제당 본문 400~700자, 허용 태그 `<p> <strong> <em> <ul> <li>`만.
- 말투는 `app.prompts.opinions.TOSS_TONE` 재사용. Slack mrkdwn 굵게는 `*x*`.
- 수신자 `servers1@naver.com` (morning-brief `config.sh`의 `BRIEF_MAIL_TO`).
- 테스트는 `.venv/bin/python -m pytest`로 실행. 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: 증권사 리포트 수집기 `naver_research`

**Files:**
- Create: `app/collector/naver_research.py`
- Create: `tests/fixtures/naver_market_list.html`, `tests/fixtures/naver_company_list.html` (EUC-KR 저장)
- Create: `tests/test_naver_research.py`
- Modify: `requirements.txt` (pypdf, beautifulsoup4 추가)

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class ResearchReport:
      category: str; title: str; broker: str; date: date
      ticker: str | None; pdf_url: str | None; read_url: str
      excerpt: str; views: int
  def parse_list_page(html: str, category: str) -> list[ResearchReport]   # excerpt="" 상태
  def extract_pdf_text(data: bytes, max_pages: int = 3) -> str
  def extract_read_text(html: str) -> str
  async def collect_reports(target: date | None = None) -> list[ResearchReport]
  ```

- [ ] **Step 1: 픽스처 저장**

```bash
S=/private/tmp/claude-501/-Users-bok/60695d6b-5128-47b9-93f7-3d2420a7e9b4/scratchpad
mkdir -p tests/fixtures
cp $S/naver.html tests/fixtures/naver_market_list.html   # 시황, 2026-09-09
curl -s -A "Mozilla/5.0" https://finance.naver.com/research/company_list.naver > tests/fixtures/naver_company_list.html
```

- [ ] **Step 2: 실패 테스트 작성** — `tests/test_naver_research.py`

```python
from datetime import date
from pathlib import Path
from app.collector.naver_research import parse_list_page, extract_read_text, ResearchReport

FIX = Path(__file__).parent / "fixtures"
def _load(name): return (FIX / name).read_bytes().decode("euc-kr", errors="ignore")

def test_parse_market_list_rows():
    rows = parse_list_page(_load("naver_market_list.html"), "시황")
    assert rows and all(isinstance(r, ResearchReport) for r in rows)
    r = next(r for r in rows if r.broker == "SK증권")
    assert r.pdf_url.endswith(".pdf") and r.date == date(2026, 9, 9) and r.ticker is None
    assert r.read_url.startswith("https://finance.naver.com/research/market_info_read.naver?nid=")

def test_parse_row_without_pdf():
    rows = parse_list_page(_load("naver_market_list.html"), "시황")
    assert any(r.pdf_url is None for r in rows)

def test_parse_company_list_has_ticker():
    rows = parse_list_page(_load("naver_company_list.html"), "종목")
    assert rows[0].ticker and len(rows[0].ticker) == 6

def test_extract_read_text_strips_tags():
    html = '<td colspan="2" class="view_cnt"><p>안녕 <b>세계</b></p></td>'
    assert extract_read_text(html) == "안녕 세계"
```

- [ ] **Step 3: 실행해 실패 확인** — `pytest tests/test_naver_research.py -q` → ImportError

- [ ] **Step 4: 구현** — `app/collector/naver_research.py` (파싱은 bs4 html.parser, 날짜 `26.09.09`→date, 조회수 int; `collect_reports`는 카테고리 5개 목록을 `asyncio.gather`로 받고 당일 필터·WATCHLIST 필터·상한 적용 후 PDF/read 본문을 세마포어 5로 병렬 채움. 각 예외는 로그 후 스킵.)

- [ ] **Step 5: 통과 확인, requirements 추가, 커밋** — `feat: 네이버 증권사 리포트 수집기 추가`

### Task 2: mrkdwn → HTML 변환기

**Files:** Create `app/publishing/mrkdwn_html.py`, `tests/test_mrkdwn_html.py`

**Interfaces:** `def mrkdwn_to_html(text: str) -> str`

- [ ] **Step 1: 테스트** — 표 기반: `*굵게*`→`<strong>`, `_기울임_`→`<em>`, `• a\n• b`→`<ul><li>a</li><li>b</li></ul>`, 단독 `===` → `<hr>`, 일반 줄 연속 → `<p>a<br>b</p>`, `&`/`<` 이스케이프.
- [ ] **Step 2: 실패 확인 → 구현 → 통과 → 커밋** `feat: Slack mrkdwn → 이메일 HTML 변환기`

### Task 3: 딥다이브 프롬프트 (2단계)

**Files:** Create `app/prompts/deep_dive.py`, `tests/test_deep_dive.py`

**Interfaces:**
```python
@dataclass
class DeepDiveTopic: headline: str; emoji: str; body_html: str; sources: list[str]
@dataclass
class DeepDive: summary: list[str]; topics: list[DeepDiveTopic]
def sanitize_html(html: str) -> str                      # 화이트리스트 p strong em ul li
def select_topics(reports, research, run_id="") -> list[dict]   # [{headline, emoji, why, report_idx:[...], research_keys:[...]}]
def write_topic(sel: dict, reports, research, run_id="") -> DeepDiveTopic | None
async def build_deep_dive(overview: str, research: dict, reports: list, run_id="") -> DeepDive | None
```

- [ ] **Step 1: 테스트** — `get_provider`를 patch해 가짜 provider 주입. (a) 선정 JSON 파싱: 코드블록 감싼 JSON, 4개 오면 3개로 자름, 1개면 None. (b) `sanitize_html`이 `<script>`·`onclick` 제거하고 허용 태그 유지. (c) 주제 1개 write 실패(예외) 시 나머지 주제로 DeepDive 반환. (d) 리포트 0건이어도 웹 리서치만으로 호출됨.
- [ ] **Step 2: 실패 확인 → 구현 → 통과 → 커밋** `feat: 딥다이브 주제 선정·본문 생성 프롬프트`

### Task 4: 이메일 템플릿 `render_daily_brief`

**Files:** Create `templates/email_daily_brief.html`; Modify `app/publishing/email_template.py`; Modify `tests/test_email_template.py`

**Interfaces:** `def render_daily_brief(*, brief_date: date, overview_html: str, opinions_html: str, deep_dive: DeepDive | None, run_id: str = "") -> tuple[str, str]` → `(subject, html)`. subject = `"A / B / C | 9월 10일 아침 브리핑"` (딥다이브 없으면 `"9월 10일 아침 브리핑"`).

- [ ] **Step 1: 테스트** — 딥다이브 있음: subject에 슬래시 목차, 본문에 "전체 요약"·각 headline·출처 문구·안내 박스 문구 "투자 권유". 딥다이브 없음: "전체 요약" 미포함, subject 날짜만.
- [ ] **Step 2: 템플릿** — 600px 카드, 로고, 제목, 회색 안내 박스, 형광펜 헤더(`background:#FFF3B0`), 대시보드, 5인 시선, 주제별 섹션, 푸터(run_id).
- [ ] **Step 3: 통과 → 커밋** `feat: 아침 브리핑 전문 이메일 템플릿`

### Task 5: morning-brief 러너 전환 (레포 밖, git 없음)

**Files:** Modify `~/Project/morning-brief/run.py`, `~/Project/morning-brief/config.sh`

- [ ] **Step 1:** `config.sh`에 `export BRIEF_MAIL_TO="servers1@naver.com"` 추가.
- [ ] **Step 2:** `run.py`: `collect_reports()`를 gather에 추가 → overview/opinions → `build_deep_dive` → `mrkdwn_to_html` → `render_daily_brief` → `send_email(MAIL_TO, subject, html)`; 실패 시 `sys.exit(1)`. `--no-send`면 `morning-brief/preview.html` 저장. Slack 호출 제거.
- [ ] **Step 3:** `--no-send`로 실행해 preview.html 브라우저 확인 (렌더 깨짐·빈 섹션 점검).
- [ ] **Step 4:** 실발송 1회 (`run.py` 기본 모드, 게이트 우회해 직접 실행). 로그에 `이메일 발송 완료` 확인.

### Task 6: 마무리

- [ ] 전체 테스트 `pytest -q` 통과 확인.
- [ ] `config.sh` Slack 변수는 사용자가 수신 확인한 뒤 삭제 (이번 세션에서는 남김).
- [ ] `/pr`로 PR 생성.
