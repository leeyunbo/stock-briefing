"""딥다이브 — 증권사 리포트 + 웹 리서치로 '오늘 시장의 큰 흐름' 2가지를 토스 리서치식으로 쉽게 쓴다.

목적(사용자 확정, 2026-09-12): 종목 추천이 아니라 거시 흐름 이해. 매일 읽으면 투자 방향을 스스로
생각할 수 있는 수준이 되는 것. 투자 초심자(함께 읽는 사람)도 이해할 수 있게.

형식:
- 제목 = 주제별 짧은 목차 문구를 " / "로 연결.
- 오늘 시장 한 줄 = 문장 하나.
- 주제(2개) = 형광펜 헤더 "문장형 헤드라인 (주 출처)" + 3단 섹션
  「무슨 일이에요?」→「왜 중요해요?」→「그래서요?」각 2문장, "~해요"체, 주제당 350자 안팎.

2단계:
1) select_topics: 리포트 목록 + 웹 리서치 요약 → 거시 주제 JSON.
2) write_topic: 주제별 근거 자료 → <p> 3개(각 <strong>소제목</strong>으로 시작). 길면 1회 압축. 병렬.
마지막에 한 줄 요약. 모든 실패는 축소(None/빈 리스트).
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

MIN_TOPICS = 1
MAX_TOPICS = 2
SECTION_LABELS = ("무슨 일이에요?", "왜 중요해요?", "그래서요?")
ALLOWED_TAGS = {"p", "strong", "em"}
MAX_PARAGRAPHS = len(SECTION_LABELS)
MAX_BODY_CHARS = 450        # 이 이상이면 1회 압축 재작성
TARGET_BODY_CHARS = 350
MAX_SOURCES = 3             # 자료 줄에 표기할 리포트 수
_EXCERPT_FOR_SELECT = 300   # 선정 단계엔 리포트 발췌 앞부분만
_RESEARCH_FOR_WRITE = 2500  # 작성 단계 웹 리서치 상한(키당)
_TRIES = 3
_RETRY_SLEEP = 5  # 초 × 시도 횟수 (CLI 한도·빈 응답 같은 일시 실패 대비)


@dataclass
class DeepDiveTopic:
    title: str        # 제목 목차용 짧은 문구 (예: 금리, 내리는 게 아니라 올린다?)
    headline: str     # 섹션 헤더 문장 (예: 연준이 금리를 올릴 수도 있어요)
    emoji: str
    source: str       # 주 출처 기관 (예: 신한투자증권) — 헤더 괄호에 표기
    body_html: str    # <p> 3개, 각 <strong>소제목</strong>으로 시작
    sources: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return f"{self.headline} ({self.source})" if self.source else self.headline

    @property
    def sections(self) -> list[tuple[str, str]]:
        """(소제목, 본문 HTML) 목록. 소제목 없는 문단은 라벨 ""."""
        out: list[tuple[str, str]] = []
        for p in BeautifulSoup(self.body_html, "html.parser").find_all("p"):
            first = p.find("strong")
            label = ""
            if first is not None and p.contents and p.contents[0] is first:
                label = first.get_text(strip=True).rstrip(":：")
                first.decompose()
            inner = p.decode_contents().strip().lstrip(":： ")
            if inner:
                out.append((label, inner))
        return out


@dataclass
class DeepDive:
    summary: list[str]  # 한 줄(요소 1개)
    topics: list[DeepDiveTopic]


TONE = """[문체 — 토스 리서치처럼]
- 친구에게 설명하듯 "~해요"체. 짧은 문장. 한 문장에 정보 하나.
- 투자 초심자가 읽습니다. 어려운 용어는 처음 나올 때 한 번만 쉬운 말로 풀어요.
  예: "10년물 국채 금리(미국 정부가 10년 돈을 빌릴 때 내는 이자)". 두 번째부터는 그냥 써요.
- 숫자는 꼭 비교 기준과 함께. 예: "4.85%로 2023년 11월 이후 가장 높아요".
- 감탄·과장·홍보 금지. 출처는 기관명만 괄호로."""


SELECT_SYSTEM = """당신은 투자 초심자도 읽는 아침 뉴스레터의 에디터입니다.
오늘 나온 증권사 리포트 목록과 웹 리서치 요약을 읽고, '지금 시장이 왜 이렇게 움직이는지'를 이해하는 데
가장 중요한 *거시 흐름* 주제 2개를 고릅니다.

[반드시 지킬 것]
- 개별 종목·종목 추천·목표주가는 주제로 삼지 않습니다. 종목은 흐름을 설명하는 예시로만 등장할 수 있어요.
- 거시 흐름 = 금리·물가·환율·유가·경기·중앙은행/정부 정책·수급·큰 산업 사이클(반도체·AI 투자·에너지 등).

[선정 기준 — 중요한 순서]
1. 오늘 시장 움직임의 *원인*을 설명하는가 (지수가 왜 올랐/내렸는지, 돈이 어디로 가는지).
2. 기관(증권사·중앙은행·통계기관)의 구체적 숫자가 있는가.
3. 하루짜리가 아니라 몇 주~몇 달 가는 흐름인가.
4. 두 주제의 축이 다르게 — 예: 하나는 금리/거시, 하나는 산업 사이클 또는 한국 시장.

[출력] JSON 배열만. 설명 금지. 각 원소:
{"title": "제목 목차용 10~14자 문구. 예: 금리, 내리는 게 아니라 올린다?",
 "headline": "섹션 헤더 문장, 쉬운 말. 예: 연준이 금리를 올릴 수도 있어요",
 "emoji": "섹션 앵커 이모지 1개 (🇺🇸 🇰🇷 🌍 🛢️ 💵 🏦 💾 ⚡ 등)",
 "source": "주 출처 기관 짧게. 예: 신한투자증권, 미 연준. 없으면 빈 문자열",
 "why": "왜 오늘 이 주제인지 한 문장",
 "report_idx": [근거가 되는 리포트 번호들],
 "research_keys": [관련 웹 리서치 키: "market" | "themes"]}"""


WRITE_SYSTEM = """당신은 투자 초심자도 읽는 아침 뉴스레터의 필자입니다. 아래 근거 자료(증권사 리포트 발췌 + 웹 리서치)만 사용해
오늘의 주제 하나를 씁니다. 자료에 없는 숫자·사실은 절대 쓰지 않습니다.

[구성 — 정확히 문단 3개, 각 문단은 <strong>소제목</strong>으로 시작]
<p><strong>무슨 일이에요?</strong> 무슨 일이 있었고 숫자가 무엇인지, 2문장.</p>
<p><strong>왜 중요해요?</strong> 그 숫자가 시장·경제에 어떤 의미인지, 인과 관계로 2문장. (예: 금리가 오르면 → 미래 이익이 큰 성장주가 불리해져요)</p>
<p><strong>그래서요?</strong> 앞으로 무엇을 지켜보면 되는지, 어떤 국면인지 2문장. 마지막 문장은 "다만 ~" 단서.</p>

[절대 금지]
- 사라/팔아라/비중을 늘려라 같은 매매 지시. 특정 종목 추천. "그래서요?"는 판단 재료까지만.
- 소제목 외의 제목, 불릿, 표, 마크다운, 코드블록.

{tone}

[출력 규칙]
- 전체 {target}자 안팎(공백 포함). 절대 {limit}자를 넘기지 않습니다.
- HTML만 출력. <p> 3개. 소제목 외에 <strong>은 핵심 숫자 한 곳에만."""


COMPRESS_SYSTEM = """아래 글을 같은 문체("~해요"체)로 {target}자 안팎으로 압축합니다.
<p> 3개와 각 문단 첫머리의 <strong>소제목</strong>은 그대로 두고, 숫자·출처·"다만" 단서는 남기고 수식어와 반복을 지웁니다.
HTML <p> 3개만 출력."""


SUMMARY_SYSTEM = """아래 주제들을 읽고 '오늘 시장을 한 문장으로' 정리합니다.
투자 초심자도 이해하는 "~해요"체 한 문장, 60자 안팎, 핵심 숫자 하나 포함. 용어 풀이 괄호 금지.
[출력] 문장 하나만. 불릿·따옴표·다른 말 금지."""


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
    return [k for k in ("market", "themes") if research.get(k)]


def _research_text(research: dict, key: str) -> str:
    return (research.get(key) or "")[:_RESEARCH_FOR_WRITE]


# ── 1단계: 주제 선정 ──

def select_topics(reports: list[ResearchReport], research: dict, run_id: str = "") -> list[dict]:
    """거시 주제 1~2개를 dict 리스트로 반환. 실패 시 빈 리스트."""
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
    """문단 3개·글자 상한을 강제한다. 넘치면 1회 압축 재작성, 그래도 넘치면 문단만 자른다."""
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
    sources = sources[:MAX_SOURCES]

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
    """'오늘 시장 한 줄' — 문장 하나를 리스트(길이 1)로."""
    text = "\n\n".join(
        f"## {t.headline}\n{BeautifulSoup(t.body_html, 'html.parser').get_text(' ')}" for t in topics
    )
    provider = get_provider(pipeline="morning_briefing", stage="deep_dive:summary", run_id=run_id)
    try:
        raw = _call(provider, SUMMARY_SYSTEM, "[전체 요약]\n" + text, "summary")
    except Exception as e:
        logger.warning("딥다이브 요약 실패: %s", e)
        return []
    lines = [re.sub(r"^[-•*]\s*", "", ln).strip().strip('"“”') for ln in strip_code_block(raw).splitlines() if ln.strip()]
    lines = [ln.replace("**", "") for ln in lines if ln]
    return lines[:1]


# ── 진입점 ──

async def build_deep_dive(research: dict, reports: list[ResearchReport], run_id: str = "") -> DeepDive | None:
    """주제 선정 → 본문 병렬 작성 → 한 줄 요약. 주제가 하나도 안 나오면 None."""
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
