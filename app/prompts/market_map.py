"""시장 지도 — '같은 변수 몇 개를 계속 추적'하는 아침 브리핑 (2026-09-13 사용자 확정).

구성:
1. 큰 줄기(threads) 3~4개: 지금 시장을 움직이는 서사. 한 줄 현황 + 어제 대비 방향(up/flat/down/new).
   상태는 호출자(러너)가 파일로 보관해 넘겨준다. 이 모듈은 순수 함수.
2. 오늘 달라진 것(change) 하나: 어제와 비교해 정말 새로 생긴 것만, 문단 2개. 없으면 None.
3. 오늘의 개념(concept) 하나: 오늘 내용에 나온 용어 하나를 3줄로.
4. 이번 주 지켜볼 일정(watch) 1~2개.

LLM 호출은 1회(JSON). 재시도 3회. 실패 시 None → 러너가 '흐름 없음' 안내 발송.
토요일(주 1회)엔 reset=True로 줄기를 처음부터 다시 잡는다.
"""

from __future__ import annotations

import json
import logging
import re
import time
from asyncio import to_thread
from dataclasses import asdict, dataclass, field
from datetime import date

from bs4 import BeautifulSoup

from app.collector.naver_research import ResearchReport
from app.summarizer import get_provider

logger = logging.getLogger(__name__)

MAX_THREADS = 4
MIN_THREADS = 2
DIRECTIONS = ("up", "flat", "down", "new")
STATUS_MAX_CHARS = 70
CHANGE_MAX_PARAGRAPHS = 2
CHANGE_MAX_CHARS = 400
CONCEPT_MAX_CHARS = 200
MAX_WATCH = 2
MAX_SOURCES = 3
ALLOWED_TAGS = {"p", "strong", "em"}
_EXCERPT_FOR_PROMPT = 700
_RESEARCH_FOR_PROMPT = 2500
_TRIES = 3
_RETRY_SLEEP = 5


@dataclass
class Thread:
    id: str              # 영문 슬러그. 날짜가 바뀌어도 같은 줄기면 같은 id
    title: str           # 예: 유가발 금리 인상 우려
    status: str          # 오늘 한 줄 현황
    direction: str       # up | flat | down | new  (어제 대비 이 서사의 강도)
    since: str = ""      # YYYY-MM-DD 처음 등장한 날


@dataclass
class Change:
    title: str           # 제목 목차용 짧은 문구
    headline: str        # 형광펜 헤더 문장
    emoji: str
    source: str          # 주 출처 기관
    body_html: str       # <p> 2개
    sources: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return f"{self.headline} ({self.source})" if self.source else self.headline


@dataclass
class Concept:
    term: str
    text: str


@dataclass
class MarketBrief:
    one_liner: str
    threads: list[Thread]
    change: Change | None
    concept: Concept | None
    watch: list[str]


TONE = """[문체 — 토스 리서치처럼]
- 친구에게 설명하듯 "~해요"체. 짧은 문장. 한 문장에 정보 하나.
- 투자 초심자가 함께 읽어요. 본문에서는 용어 풀이 괄호를 쓰지 말고, 설명이 필요한 용어는 '오늘의 개념'에서 딱 하나만 풀어요.
- 숫자는 꼭 비교 기준과 함께. 예: "4.96%로 2023년 이후 가장 높아요".
- 사라/팔아라/비중 조절 같은 매매 지시, 특정 종목 추천 금지. 판단 재료까지만.
- 감탄·과장·홍보 금지. 출처는 기관명만 괄호로."""


SYSTEM = """당신은 투자 초심자도 읽는 아침 뉴스레터의 에디터입니다. 목표는 독자가 '지금 시장이 왜 이렇게 움직이는지'를
같은 변수 몇 개를 매일 추적하며 이해하게 하는 것입니다. 종목 추천이 아닙니다.

오늘 자료(증권사 리포트 발췌 + 웹 리서치)와 '어제까지의 큰 줄기'를 읽고 아래 JSON 하나를 만듭니다.

[1. threads — 큰 줄기 {min}~{max}개]
- 지금 시장을 움직이는 거시 서사: 금리·물가·환율·유가·경기·정책·수급·큰 산업 사이클.
- 어제 줄기가 있으면 *같은 id를 유지*하고 status를 오늘 기준으로 고쳐 씁니다. direction은 어제 대비 그 서사의 강도:
  "up"(더 강해짐/악화·심화) · "flat"(비슷) · "down"(약해짐/완화) · "new"(오늘 새로 추가).
- 더 이상 시장을 움직이지 않는 줄기는 빼고, 새로 생긴 줄기는 추가합니다. 개별 종목은 줄기가 될 수 없습니다.
- status는 {status_max}자 이내 한 문장, 숫자 하나 포함.
{reset_note}
[2. change — 오늘 달라진 것 하나, 또는 null]
- 어제 줄기와 비교해 *정말 새로 생긴 사실*(새 데이터·정책·이벤트)만. 어제와 같은 이야기에 숫자만 바뀐 건 null.
- body는 HTML <p> 2개. 1문단: 무슨 일이 있었고 숫자가 무엇인지, 왜 중요한지. 2문단: 앞으로 무엇을 지켜보면 되는지 + "다만 ~" 단서.
  전체 {change_max}자 이내. <strong>은 핵심 숫자 한 곳.

[3. concept — 오늘의 개념 하나]
- 오늘 threads/change에 등장한 용어 중 초심자가 막힐 것 하나. term + text(3문장, {concept_max}자 이내). 이미 어제까지 다룬 개념(recent_concepts)은 피합니다.

[4. one_liner — 오늘 시장 한 줄] 60자 안팎, 숫자 하나.
[5. watch — 이번 주 지켜볼 일정 {max_watch}개 이내] "9/16(화) FOMC 금리 결정" 형식. 자료에 있는 것만.

{tone}

[출력] JSON 객체만. 설명·코드블록 금지.
{{"one_liner": "...",
 "threads": [{{"id": "oil-rates", "title": "유가발 금리 인상 우려", "status": "...", "direction": "up|flat|down|new"}}],
 "change": {{"title": "목차용 10~14자", "headline": "쉬운 문장형 헤드라인", "emoji": "이모지 1개", "source": "주 출처 기관",
            "body": "<p>...</p><p>...</p>", "report_idx": [근거 리포트 번호]}} 또는 null,
 "concept": {{"term": "...", "text": "..."}},
 "watch": ["...", "..."]}}"""

RESET_NOTE = "- (주 1회 재정비) 어제 줄기는 참고만 하고, 오늘 자료 기준으로 줄기를 처음부터 다시 잡습니다. 이 경우 direction은 모두 \"new\".\n"


# ── 유틸 ──

def _call(provider, system: str, user: str, label: str) -> str:
    last: Exception | None = None
    for i in range(_TRIES):
        try:
            out = provider.call(system, user)
            if out and out.strip():
                return out
            last = RuntimeError("빈 응답")
        except Exception as e:
            last = e
        logger.warning("시장지도 %s 시도 %d/%d 실패: %s", label, i + 1, _TRIES, last)
        if i < _TRIES - 1:
            time.sleep(_RETRY_SLEEP * (i + 1))
    raise last or RuntimeError("호출 실패")


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for bad in soup.find_all(["script", "style"]):
        bad.decompose()
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}
    return str(soup).strip()


def _paragraphs(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ps = [str(p) for p in soup.find_all("p") if p.get_text(strip=True)]
    if ps:
        return ps
    text = html.strip()
    return [f"<p>{text}</p>"] if text else []


def _text_len(html: str) -> int:
    return len(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def _strip_fence(raw: str) -> str:
    """```json ... ``` 펜스만 벗긴다. (summarizer.strip_code_block은 마지막 HTML 태그 뒤를 잘라내 JSON을 망가뜨림)"""
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_object(raw: str) -> dict:
    text = _strip_fence(raw)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("JSON 객체 없음")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("객체 아님")
    return data


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    return s[:40] or "thread"


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _source_label(r: ResearchReport) -> str:
    return f"{r.broker} · {r.title} ({r.date.month}/{r.date.day})"


# ── 프롬프트 조립 ──

def build_user_prompt(
    reports: list[ResearchReport], research: dict, prev_threads: list[Thread], recent_concepts: list[str], today: date
) -> str:
    lines = [f"[오늘] {today.isoformat()}", "\n[어제까지의 큰 줄기]"]
    if prev_threads:
        for t in prev_threads:
            lines.append(f"- id={t.id} | {t.title} | {t.status} | since {t.since}")
    else:
        lines.append("(없음 — 첫 실행)")
    lines.append("\n[최근 다룬 개념] " + (", ".join(recent_concepts) if recent_concepts else "(없음)"))
    lines.append("\n[리포트 목록]")
    for i, r in enumerate(reports):
        excerpt = re.sub(r"\s+", " ", r.excerpt)[:_EXCERPT_FOR_PROMPT]
        lines.append(f"#{i} [{r.category}] {r.broker} — {r.title}\n    {excerpt}")
    if not reports:
        lines.append("(오늘 수집된 리포트 없음)")
    lines.append("\n[웹 리서치]")
    for key in ("market", "themes"):
        if research.get(key):
            lines.append(f"## {key}\n{research[key][:_RESEARCH_FOR_PROMPT]}")
    return "\n".join(lines)


# ── 응답 → 구조체 ──

def parse_brief(data: dict, reports: list[ResearchReport], prev_threads: list[Thread], today: date) -> MarketBrief | None:
    prev_by_id = {t.id: t for t in prev_threads}
    threads: list[Thread] = []
    for it in data.get("threads") or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        tid = _slug(it.get("id") or it["title"])
        direction = str(it.get("direction") or "").lower()
        if tid not in prev_by_id:
            direction = "new"
        elif direction not in DIRECTIONS or direction == "new":
            direction = "flat"
        threads.append(Thread(
            id=tid,
            title=_clip(it["title"], 30),
            status=_clip(it.get("status") or "", STATUS_MAX_CHARS),
            direction=direction,
            since=prev_by_id[tid].since if tid in prev_by_id and prev_by_id[tid].since else today.isoformat(),
        ))
        if len(threads) >= MAX_THREADS:
            break
    if len(threads) < MIN_THREADS:
        logger.warning("시장지도 줄기 부족: %d개", len(threads))
        return None

    change = None
    c = data.get("change")
    if isinstance(c, dict) and (c.get("headline") or c.get("title")):
        body = sanitize_html(str(c.get("body") or ""))
        paras = _paragraphs(body)[:CHANGE_MAX_PARAGRAPHS]
        body = "".join(paras)
        if body and _text_len(body) > CHANGE_MAX_CHARS:
            logger.info("시장지도 change 길이 초과 %d자 → 첫 문단만", _text_len(body))
            body = paras[0]
        if body:
            idx = [i for i in (c.get("report_idx") or []) if isinstance(i, int) and 0 <= i < len(reports)]
            sources = [_source_label(reports[i]) for i in idx][:MAX_SOURCES] or ["웹 리서치"]
            headline = str(c.get("headline") or c.get("title")).strip()
            change = Change(
                title=_clip(c.get("title") or headline, 20),
                headline=headline,
                emoji=str(c.get("emoji") or "📌").strip(),
                source=str(c.get("source") or "").strip(),
                body_html=body,
                sources=sources,
            )

    concept = None
    k = data.get("concept")
    if isinstance(k, dict) and k.get("term") and k.get("text"):
        concept = Concept(term=_clip(k["term"], 30), text=_clip(k["text"], CONCEPT_MAX_CHARS))

    watch = [_clip(w, 60) for w in (data.get("watch") or []) if isinstance(w, str) and w.strip()][:MAX_WATCH]
    one_liner = _clip(data.get("one_liner") or "", 90)
    return MarketBrief(one_liner=one_liner, threads=threads, change=change, concept=concept, watch=watch)


# ── 진입점 ──

def build_market_brief_sync(
    research: dict,
    reports: list[ResearchReport],
    prev_threads: list[Thread],
    recent_concepts: list[str],
    today: date,
    reset: bool = False,
    run_id: str = "",
) -> MarketBrief | None:
    system = SYSTEM.format(
        min=MIN_THREADS, max=MAX_THREADS, status_max=STATUS_MAX_CHARS, change_max=CHANGE_MAX_CHARS,
        concept_max=CONCEPT_MAX_CHARS, max_watch=MAX_WATCH, tone=TONE,
        reset_note=RESET_NOTE if reset else "",
    )
    user = build_user_prompt(reports, research, [] if reset else prev_threads, recent_concepts, today)
    provider = get_provider(pipeline="morning_briefing", stage="market_map", run_id=run_id)
    try:
        raw = _call(provider, system, user, "brief")
        data = _parse_json_object(raw)
    except Exception as e:
        logger.warning("시장지도 생성 실패: %s", e)
        return None
    brief = parse_brief(data, reports, [] if reset else prev_threads, today)
    if brief:
        logger.info(
            "시장지도 완료: 줄기 %d개 [%s], 달라진 것 %s, 개념 %s",
            len(brief.threads),
            ", ".join(f"{t.title}({t.direction})" for t in brief.threads),
            brief.change.title if brief.change else "없음",
            brief.concept.term if brief.concept else "없음",
        )
    return brief


async def build_market_brief(
    research: dict,
    reports: list[ResearchReport],
    prev_threads: list[Thread],
    recent_concepts: list[str],
    today: date,
    reset: bool = False,
    run_id: str = "",
) -> MarketBrief | None:
    logger.info("시장지도 시작: 리포트 %d건, 어제 줄기 %d개, reset=%s", len(reports), len(prev_threads), reset)
    return await to_thread(build_market_brief_sync, research, reports, prev_threads, recent_concepts, today, reset, run_id)


# ── 상태 직렬화 (러너가 파일로 보관) ──

def threads_to_state(brief: MarketBrief, today: date, prev_concepts: list[str]) -> dict:
    concepts = ([brief.concept.term] if brief.concept else []) + [c for c in prev_concepts if not brief.concept or c != brief.concept.term]
    return {
        "updated": today.isoformat(),
        "threads": [asdict(t) for t in brief.threads],
        "recent_concepts": concepts[:10],
    }


def threads_from_state(state: dict | None) -> tuple[list[Thread], list[str]]:
    if not state:
        return [], []
    threads = []
    for t in state.get("threads") or []:
        try:
            threads.append(Thread(id=t["id"], title=t["title"], status=t.get("status", ""),
                                  direction=t.get("direction", "flat"), since=t.get("since", "")))
        except (KeyError, TypeError):
            continue
    return threads, [c for c in (state.get("recent_concepts") or []) if isinstance(c, str)]
