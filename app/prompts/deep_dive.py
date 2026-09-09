"""딥다이브 — 증권사 리포트 + 웹 리서치로 주제 2~3개를 골라 끝까지 파는 글을 쓴다.

2단계:
1) select_topics: 리포트 목록 + 웹 리서치 요약을 보고 주제 2~3개를 JSON으로 선정.
2) write_topic: 주제별 근거 리포트 전문 + 관련 웹 리서치로 본문(제한된 HTML) 작성. 병렬.
마지막에 전체 요약 불릿을 한 번 더 뽑는다. 모든 실패는 축소(None/빈 리스트).
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
from app.prompts.opinions import TOSS_TONE
from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)

MIN_TOPICS = 2
MAX_TOPICS = 3
ALLOWED_TAGS = {"p", "strong", "em", "ul", "li"}
_EXCERPT_FOR_SELECT = 300   # 선정 단계엔 리포트 발췌 앞부분만
_RESEARCH_FOR_WRITE = 2500  # 작성 단계 웹 리서치 상한(키당)
_TRIES = 3
_RETRY_SLEEP = 5  # 초 × 시도 횟수 (CLI 한도·빈 응답 같은 일시 실패 대비)


@dataclass
class DeepDiveTopic:
    headline: str
    emoji: str
    body_html: str
    sources: list[str] = field(default_factory=list)


@dataclass
class DeepDive:
    summary: list[str]
    topics: list[DeepDiveTopic]


SELECT_SYSTEM = """당신은 중장기 투자자 한 명을 위한 리서치 에디터예요.
오늘 나온 증권사 리포트 목록과 웹 리서치 요약을 읽고, 오늘 깊게 다룰 주제 2~3개를 고르세요.

[선정 기준 — 중요한 순서]
1. 1차 출처의 *구체적 숫자*가 있는가 (지표·밸류·실적·수주 금액 등). 숫자 없는 주제는 뒤로.
2. 내 레이더(마벨·아마존·알파벳·네이버·SK하이닉스)나 테마(반도체·AI SW·로봇·M7)와 연관되면 가산점.
3. 하루짜리 등락이 아니라 몇 주~몇 달 가는 흐름인가.
4. 주제끼리 겹치지 않게 — 한국 시장 / 미국·거시 / 산업·테마처럼 축이 다르면 좋아요.

[출력] JSON 배열만. 설명 금지. 각 원소:
{"headline": "제목 목차용 12자 내외 문구 (예: 버블 경보가 풀린 코스피?)",
 "emoji": "섹션 앵커 이모지 1개 (🇰🇷 🇺🇸 🌍 🔬 🤖 💾 ⚡ 등)",
 "why": "왜 오늘 이 주제인지 한 문장",
 "report_idx": [근거가 되는 리포트 번호들],
 "research_keys": [관련 웹 리서치 키: "market" | "themes" | 종목 티커]}"""


WRITE_SYSTEM = """당신은 중장기 투자자 한 명을 위해 오늘의 주제 하나를 끝까지 파는 리서치 작가예요.
아래 근거 자료(증권사 리포트 발췌 + 웹 리서치)만 사용해서 쓰세요. 자료에 없는 숫자·사실은 절대 지어내지 마세요.

[글 구조 — 이 순서로, 소제목 없이 문단으로 자연스럽게]
1. 데이터: 어떤 숫자가 나왔나. 출처(증권사/기관)를 괄호로.
2. 해석: 그 숫자가 뜻하는 것. 과거 이력·비교 대상이 있으면 함께.
3. 결론: 그래서 어떻게 봐야 하나. "안전해졌다 ≠ 상승 베팅"처럼 한 줄로 못 박아요.
4. 실행 아이디어: 중장기 투자자가 할 수 있는 것 (자료에 있을 때만, 없으면 생략).
5. 반론: 이 결론이 틀릴 수 있는 이유 한 가지.

{tone}

[출력 규칙]
- 분량 400~700자. 문단 3~5개.
- HTML만 출력. 허용 태그: <p> <strong> <em> <ul> <li>. 그 외 태그·마크다운·코드블록 금지.
- 핵심 숫자와 결론 문장은 <strong>으로."""


SUMMARY_SYSTEM = """아래 딥다이브 주제들을 읽고 '오늘 이것만 알면 되는' 전체 요약을 불릿 2~3개로 써요.
각 불릿은 한 문장, 숫자 하나 이상 포함. {tone}
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
        if not isinstance(it, dict) or not it.get("headline"):
            continue
        idx = [i for i in (it.get("report_idx") or []) if isinstance(i, int) and 0 <= i < len(reports)]
        keys = [k for k in (it.get("research_keys") or []) if k in valid_keys]
        out.append({
            "headline": str(it["headline"]).strip(),
            "emoji": str(it.get("emoji") or "📌").strip(),
            "why": str(it.get("why") or "").strip(),
            "report_idx": idx,
            "research_keys": keys,
        })
    if len(out) < MIN_TOPICS:
        logger.warning("딥다이브 주제 부족: %d개", len(out))
        return []
    return out


# ── 2단계: 본문 작성 ──

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
    try:
        raw = _call(provider, WRITE_SYSTEM.format(tone=TOSS_TONE), "\n".join(parts), f"write:{sel['headline']}")
    except Exception as e:
        logger.warning("딥다이브 본문 실패 (%s): %s", sel["headline"], e)
        return None
    body = sanitize_html(strip_code_block(raw))
    if not body:
        logger.warning("딥다이브 본문 비어 있음 (%s)", sel["headline"])
        return None
    logger.info("딥다이브 본문 완료: %s (%d자)", sel["headline"], len(body))
    return DeepDiveTopic(headline=sel["headline"], emoji=sel["emoji"], body_html=body, sources=sources)


def _summarize(topics: list[DeepDiveTopic], run_id: str = "") -> list[str]:
    text = "\n\n".join(f"## {t.headline}\n{BeautifulSoup(t.body_html, 'html.parser').get_text(' ')}" for t in topics)
    provider = get_provider(pipeline="morning_briefing", stage="deep_dive:summary", run_id=run_id)
    try:
        raw = _call(provider, SUMMARY_SYSTEM.format(tone=TOSS_TONE), "[전체 요약]\n" + text, "summary")
    except Exception as e:
        logger.warning("딥다이브 요약 실패: %s", e)
        return []
    bullets = [re.sub(r"^[-•*]\s*", "", ln).strip() for ln in strip_code_block(raw).splitlines() if ln.strip()]
    return [b.replace("**", "") for b in bullets if b][:3]


# ── 진입점 ──

async def build_deep_dive(
    overview: str, research: dict, reports: list[ResearchReport], run_id: str = ""
) -> DeepDive | None:
    """주제 선정 → 본문 병렬 작성 → 요약. 주제가 하나도 안 나오면 None."""
    del overview  # 현재는 리포트+웹 리서치만 사용. 시그니처는 스펙 유지.
    logger.info("딥다이브 시작: 리포트 %d건", len(reports))
    selected = await to_thread(select_topics, reports, research, run_id)
    if not selected:
        return None
    logger.info("딥다이브 주제 선정: %s", " / ".join(s["headline"] for s in selected))

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
