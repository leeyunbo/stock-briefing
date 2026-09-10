"""딥다이브 — 증권사 리포트 + 웹 리서치로 주제 3개를 골라 '월가소식' 형식으로 쓴다.

형식(사용자가 준 뉴스레터 스크린샷 기준):
- 제목 = 주제별 짧은 목차 문구를 " / "로 연결.
- 전체 요약 = 주제당 한 줄 불릿.
- 주제별 섹션 = 형광펜 헤더 "문장형 헤드라인 (주 출처)" + 문단 2개(≈500자), 담담한 "~습니다"체.

2단계:
1) select_topics: 리포트 목록 + 웹 리서치 요약 → 주제 JSON.
2) write_topic: 주제별 근거 자료 → 본문 HTML(<p> 2개). 길면 1회 압축 재작성. 병렬.
마지막에 요약 불릿. 모든 실패는 축소(None/빈 리스트).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from asyncio import to_thread
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from app.collector.naver_research import ResearchReport
from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)

MIN_TOPICS = 2
MAX_TOPICS = 3
ALLOWED_TAGS = {"p", "strong", "em"}
MAX_PARAGRAPHS = 2
MAX_BODY_CHARS = 650        # 이 이상이면 1회 압축 재작성
TARGET_BODY_CHARS = 500
_EXCERPT_FOR_SELECT = 300   # 선정 단계엔 리포트 발췌 앞부분만
_RESEARCH_FOR_WRITE = 2500  # 작성 단계 웹 리서치 상한(키당)
_TRIES = 3
_RETRY_SLEEP = 5  # 초 × 시도 횟수 (CLI 한도·빈 응답 같은 일시 실패 대비)


@dataclass
class DeepDiveTopic:
    title: str        # 제목 목차용 짧은 문구 (예: 버블 경보가 풀린 코스피?)
    headline: str     # 섹션 헤더 문장 (예: 코스피, 버블 경보가 풀렸습니다)
    emoji: str
    source: str       # 주 출처 기관 (예: BofA) — 헤더 괄호에 표기
    body_html: str
    sources: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return f"{self.headline} ({self.source})" if self.source else self.headline


@dataclass
class DeepDive:
    summary: list[str]
    topics: list[DeepDiveTopic]


TONE = """[문체]
- 신문 해설 기사처럼 담담한 "~습니다"체. 감탄·권유·따뜻한 말투 금지.
- 용어 풀이용 괄호 금지. 괄호는 출처·수치 보충에만 씁니다. 예: (BofA), (7월 초 80% → 44.5%).
- 모든 문장에 정보가 있어야 합니다. 도입·정리·인사 문장 금지.
- 숫자는 구체적으로. 비교 기준(과거·타 지수·컨센서스)을 붙입니다."""


SELECT_SYSTEM = """당신은 개인 투자자용 아침 뉴스레터의 에디터입니다.
오늘 나온 증권사 리포트 목록과 웹 리서치 요약을 읽고, 오늘 다룰 주제 3개를 고릅니다(자료가 빈약하면 2개).

[선정 기준 — 중요한 순서]
1. 기관(증권사·IB·통계기관)의 *구체적 숫자*가 있는가. 숫자 없는 주제는 뒤로.
2. 내 레이더(마벨·아마존·알파벳·네이버·SK하이닉스)나 테마(반도체·AI SW·로봇·M7)와 연관되면 가산점.
3. 하루짜리 등락이 아니라 몇 주~몇 달 가는 흐름인가.
4. 주제끼리 축이 다르게 — 한국 시장 / 미국·거시 / 산업·테마.

[출력] JSON 배열만. 설명 금지. 각 원소:
{"title": "제목 목차용 10~14자 문구. 예: 버블 경보가 풀린 코스피?",
 "headline": "섹션 헤더 문장. 예: 코스피, 버블 경보가 풀렸습니다",
 "emoji": "섹션 앵커 이모지 1개 (🇰🇷 🇺🇸 🌍 🔬 🤖 💾 ⚡ 등)",
 "source": "이 주제의 주 출처 기관 짧게. 예: BofA, 신한투자증권, JPM. 없으면 빈 문자열",
 "why": "왜 오늘 이 주제인지 한 문장",
 "report_idx": [근거가 되는 리포트 번호들],
 "research_keys": [관련 웹 리서치 키: "market" | "themes" | 종목 티커]}"""


WRITE_SYSTEM = """당신은 개인 투자자용 아침 뉴스레터의 필자입니다. 아래 근거 자료(증권사 리포트 발췌 + 웹 리서치)만 사용해
오늘의 주제 하나를 씁니다. 자료에 없는 숫자·사실은 절대 쓰지 않습니다.

[구성 — 정확히 문단 2개]
1문단: 무슨 일이 있었고 숫자가 무엇인지. 출처 기관을 괄호로. 그 숫자가 왜 의미 있는지 한두 문장(과거 이력·비교 대상).
2문단: 결론을 한 문장으로 못 박고("안전해졌다가 아니라 상승에 베팅할 수 있다는 쪽입니다" 식), 자료에 있으면 실행 아이디어 한 문장,
      마지막에 "다만 ~" 으로 반론·단서 한 문장.

{tone}

[출력 규칙]
- 전체 {target}자 안팎(공백 포함). 절대 {limit}자를 넘기지 않습니다.
- HTML만 출력. <p> 2개, 안에서 <strong>은 핵심 숫자·결론 한 곳씩만. 그 외 태그·마크다운·코드블록·소제목 금지."""


COMPRESS_SYSTEM = """아래 글을 같은 문체("~습니다"체, 괄호 풀이 금지)로 {target}자 안팎으로 압축합니다.
문단 2개 유지. 숫자·출처·결론·"다만" 단서는 남기고 수식어와 반복을 지웁니다. HTML <p> 2개만 출력."""


SUMMARY_SYSTEM = """아래 주제들을 각각 한 문장으로 요약합니다. 주제 순서대로 한 줄씩, 주제 수만큼만.
각 문장은 핵심 숫자 하나와 결론을 담은 "~습니다"체. 용어 풀이 괄호 금지.
[출력] "- " 로 시작하는 줄만. 다른 말 금지."""


# ── 유틸 ──

def _call(provider, system: str, user: str, label: str) -> str:
    """프로바이더 호출 + 일시 실패(빈 stderr·한도·빈 응답) 백오프 재시도."""
    last: Exception | None = None
    for i in range(_TRIES):
        try:
            out = provider.call(system, user)
            if out and out.strip():
                return out
            last = RuntimeError("빈 응답")
        except Exception as e:
            last = e
        logger.warning("딥다이브 %s 시도 %d/%d 실패: %s", label, i + 1, _TRIES, last)
        if i < _TRIES - 1:
            time.sleep(_RETRY_SLEEP * (i + 1))
    raise last or RuntimeError("호출 실패")


def sanitize_html(html: str) -> str:
    """허용 태그만 남기고 나머지 태그는 벗긴다. script/style은 내용까지 제거."""
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup.find_all(["script", "style"]):
        bad.decompose()
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}
    return str(soup).strip()


def _paragraphs(html: str) -> list[str]:
    """<p>…</p> 목록. <p>가 없으면 전체를 문단 하나로 감싼다."""
    soup = BeautifulSoup(html, "html.parser")
    ps = [str(p) for p in soup.find_all("p") if p.get_text(strip=True)]
    if ps:
        return ps
    text = html.strip()
    return [f"<p>{text}</p>"] if text else []


def _text_len(html: str) -> int:
    return len(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def _parse_json_array(raw: str) -> list:
    text = strip_code_block(raw)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        raise ValueError("JSON 배열 없음")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("배열 아님")
    return data


def _source_label(r: ResearchReport) -> str:
    return f"{r.broker} · {r.title} ({r.date.month}/{r.date.day})"


def _research_keys_available(research: dict) -> list[str]:
    keys = [k for k in ("market", "themes") if research.get(k)]
    keys += [t for t, v in (research.get("stocks") or {}).items() if v]
    return keys


def _research_text(research: dict, key: str) -> str:
    if key in ("market", "themes"):
        return (research.get(key) or "")[:_RESEARCH_FOR_WRITE]
    return ((research.get("stocks") or {}).get(key) or "")[:_RESEARCH_FOR_WRITE]


# ── 1단계: 주제 선정 ──

def select_topics(reports: list[ResearchReport], research: dict, run_id: str = "") -> list[dict]:
    """주제 2~3개를 dict 리스트로 반환. 실패·부족 시 빈 리스트."""
    lines = ["[리포트 목록]"]
    for i, r in enumerate(reports):
        excerpt = re.sub(r"\s+", " ", r.excerpt)[:_EXCERPT_FOR_SELECT]
        lines.append(f"#{i} [{r.category}] {r.broker} — {r.title}\n    {excerpt}")
    if not reports:
        lines.append("(오늘 수집된 리포트 없음 — 웹 리서치만으로 선정)")
    lines.append("\n[웹 리서치 요약]")
    for key in _research_keys_available(research):
        lines.append(f"## {key}\n{_research_text(research, key)[:1200]}")

    provider = get_provider(pipeline="morning_briefing", stage="deep_dive:select", run_id=run_id)
    try:
        raw = _call(provider, SELECT_SYSTEM, "\n".join(lines), "select")
        items = _parse_json_array(raw)
    except Exception as e:
        logger.warning("딥다이브 주제 선정 실패: %s", e)
        return []

    valid_keys = set(_research_keys_available(research))
    out: list[dict] = []
    for it in items[:MAX_TOPICS]:
        if not isinstance(it, dict) or not (it.get("headline") or it.get("title")):
            continue
        headline = str(it.get("headline") or it.get("title")).strip()
        idx = [i for i in (it.get("report_idx") or []) if isinstance(i, int) and 0 <= i < len(reports)]
        keys = [k for k in (it.get("research_keys") or []) if k in valid_keys]
        out.append({
            "title": str(it.get("title") or headline).strip(),
            "headline": headline,
            "emoji": str(it.get("emoji") or "📌").strip(),
            "source": str(it.get("source") or "").strip(),
            "why": str(it.get("why") or "").strip(),
            "report_idx": idx,
            "research_keys": keys,
        })
    if len(out) < MIN_TOPICS:
        logger.warning("딥다이브 주제 부족: %d개", len(out))
        return []
    return out


# ── 2단계: 본문 작성 ──

def _fit_body(provider, body: str, label: str) -> str:
    """문단 2개·글자 상한을 강제한다. 넘치면 1회 압축 재작성, 그래도 넘치면 문단만 자른다."""
    paras = _paragraphs(body)
    if len(paras) <= MAX_PARAGRAPHS and _text_len(body) <= MAX_BODY_CHARS:
        return "".join(paras)
    logger.info("딥다이브 압축 (%s): %d문단 %d자", label, len(paras), _text_len(body))
    try:
        raw = _call(provider, COMPRESS_SYSTEM.format(target=TARGET_BODY_CHARS), "".join(paras), f"compress:{label}")
        compressed = _paragraphs(sanitize_html(strip_code_block(raw)))
        if compressed:
            paras = compressed
    except Exception as e:
        logger.warning("딥다이브 압축 실패, 원문 사용 (%s): %s", label, e)
    return "".join(paras[:MAX_PARAGRAPHS])


def write_topic(sel: dict, reports: list[ResearchReport], research: dict, run_id: str = "") -> DeepDiveTopic | None:
    """주제 하나의 본문을 쓴다. 실패 시 None."""
    parts = [f"[주제] {sel['headline']}", f"[왜 오늘] {sel.get('why', '')}", "\n[근거 자료 — 증권사 리포트]"]
    sources: list[str] = []
    for i in sel.get("report_idx", []):
        r = reports[i]
        parts.append(f"### {r.broker} — {r.title} ({r.category})\n{r.excerpt}")
        sources.append(_source_label(r))
    if not sel.get("report_idx"):
        parts.append("(해당 리포트 없음)")
    parts.append("\n[근거 자료 — 웹 리서치]")
    for key in sel.get("research_keys", []):
        parts.append(f"## {key}\n{_research_text(research, key)}")
    if not sel.get("research_keys"):
        parts.append("(없음)")
    if not sources:
        sources = ["웹 리서치"]

    provider = get_provider(pipeline="morning_briefing", stage="deep_dive:write", run_id=run_id)
    system = WRITE_SYSTEM.format(tone=TONE, target=TARGET_BODY_CHARS, limit=MAX_BODY_CHARS)
    try:
        raw = _call(provider, system, "\n".join(parts), f"write:{sel['headline']}")
    except Exception as e:
        logger.warning("딥다이브 본문 실패 (%s): %s", sel["headline"], e)
        return None
    body = sanitize_html(strip_code_block(raw))
    if not body:
        logger.warning("딥다이브 본문 비어 있음 (%s)", sel["headline"])
        return None
    body = _fit_body(provider, body, sel["headline"])
    logger.info("딥다이브 본문 완료: %s (%d자)", sel["headline"], _text_len(body))
    return DeepDiveTopic(
        title=sel.get("title") or sel["headline"],
        headline=sel["headline"],
        emoji=sel["emoji"],
        source=sel.get("source", ""),
        body_html=body,
        sources=sources,
    )


def _summarize(topics: list[DeepDiveTopic], run_id: str = "") -> list[str]:
    text = "\n\n".join(
        f"## {t.headline}\n{BeautifulSoup(t.body_html, 'html.parser').get_text(' ')}" for t in topics
    )
    provider = get_provider(pipeline="morning_briefing", stage="deep_dive:summary", run_id=run_id)
    try:
        raw = _call(provider, SUMMARY_SYSTEM, "[전체 요약]\n" + text, "summary")
    except Exception as e:
        logger.warning("딥다이브 요약 실패: %s", e)
        return []
    bullets = [re.sub(r"^[-•*]\s*", "", ln).strip() for ln in strip_code_block(raw).splitlines() if ln.strip()]
    return [b.replace("**", "") for b in bullets if b][: len(topics)]


# ── 진입점 ──

async def build_deep_dive(research: dict, reports: list[ResearchReport], run_id: str = "") -> DeepDive | None:
    """주제 선정 → 본문 병렬 작성 → 요약. 주제가 하나도 안 나오면 None."""
    logger.info("딥다이브 시작: 리포트 %d건", len(reports))
    selected = await to_thread(select_topics, reports, research, run_id)
    if not selected:
        return None
    logger.info("딥다이브 주제 선정: %s", " / ".join(s["title"] for s in selected))

    results = await asyncio.gather(
        *[to_thread(write_topic, s, reports, research, run_id) for s in selected],
        return_exceptions=True,
    )
    topics = [t for t in results if isinstance(t, DeepDiveTopic)]
    if not topics:
        logger.warning("딥다이브 본문 전부 실패")
        return None
    summary = await to_thread(_summarize, topics, run_id)
    logger.info("딥다이브 완료: 주제 %d개, 요약 %d개", len(topics), len(summary))
    return DeepDive(summary=summary, topics=topics)
