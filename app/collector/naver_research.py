"""네이버 증권 리서치 — 당일 증권사 리포트를 수집해 본문 발췌를 만든다.

소스: m.stock.naver.com/api/research/{category} (비인증 JSON). 2026-09-10 finance.naver.com 구 페이지가
stock.naver.com으로 이전(302)되어 API 기반으로 전환.
시황·투자전략·산업·경제는 당일 전부, 종목분석은 WATCHLIST 종목만.
발췌 = 상세 API의 content(증권사 요약 HTML → 텍스트) + attachUrl PDF 앞 3페이지 텍스트.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.collector.themes import WATCHLIST
from app.core.http import get_http_client

logger = logging.getLogger(__name__)

API = "https://m.stock.naver.com/api/research"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Referer": "https://stock.naver.com/research/daily"}

# 카테고리 표시명 → API 경로
CATEGORIES: dict[str, str] = {
    "시황": "market",
    "투자전략": "invest",
    "산업": "industry",
    "경제": "economy",
    "종목": "company",
}

# 거시 흐름용 (종목분석 제외). 러너 기본값.
MACRO_CATEGORIES: tuple[str, ...] = ("시황", "투자전략", "산업", "경제")

PER_CATEGORY_LIMIT = 15
TOTAL_LIMIT = 40
PDF_MAX_PAGES = 3
EXCERPT_MAX_CHARS = 6000
PAGE_SIZE = 20
MAX_LIST_PAGES = 3
_CONCURRENCY = 5
_KST = ZoneInfo("Asia/Seoul")


@dataclass
class ResearchReport:
    category: str
    title: str
    broker: str
    date: date
    ticker: str | None
    pdf_url: str | None
    read_url: str
    excerpt: str = ""
    views: int = 0
    research_id: str = ""


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text or "")
    if not m:
        return None
    return date(*(int(x) for x in m.groups()))


def _to_int(v) -> int:
    digits = re.sub(r"\D", "", str(v or ""))
    return int(digits) if digits else 0


def parse_list(items: list, category: str) -> list[ResearchReport]:
    """목록 API 응답(JSON 배열) → ResearchReport 리스트 (excerpt 비어 있음)."""
    out: list[ResearchReport] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        d = _parse_date(it.get("writeDate"))
        rid = str(it.get("researchId") or "")
        if d is None or not rid:
            continue
        out.append(
            ResearchReport(
                category=category,
                title=str(it.get("title") or "").strip(),
                broker=str(it.get("brokerName") or "").strip(),
                date=d,
                ticker=str(it["itemCode"]) if it.get("itemCode") else None,
                pdf_url=None,  # 상세 API에서 채움
                read_url=str(it.get("endUrl") or f"https://m.stock.naver.com/research/{CATEGORIES.get(category, 'market')}/{rid}"),
                views=_to_int(it.get("readCount")),
                research_id=rid,
            )
        )
    return out


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    """널 문자 등 제어 문자를 제거한다. (PDF 텍스트에 \x00이 섞이면 subprocess 인자로 못 넘김)"""
    return _CONTROL_CHARS.sub("", text or "")


def html_to_text(html: str) -> str:
    """상세 content(HTML)를 공백 정리된 텍스트로."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return clean_text(re.sub(r"\s+", " ", text)).strip()


def extract_pdf_text(data: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """PDF 앞 max_pages 페이지의 텍스트를 뽑는다."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts)
    return clean_text(re.sub(r"[ \t]+", " ", text)).strip()


async def _fetch_list(client: httpx.AsyncClient, category: str, target: date) -> list[ResearchReport]:
    """카테고리 목록을 당일 행이 끊길 때까지 페이지 순회한다."""
    rows: list[ResearchReport] = []
    path = CATEGORIES[category]
    for page in range(1, MAX_LIST_PAGES + 1):
        url = f"{API}/{path}?page={page}&pageSize={PAGE_SIZE}"
        try:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
            items = resp.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:
            logger.warning("리포트 목록 실패 (%s p%d): %s", category, page, e)
            break
        parsed = parse_list(items, category)
        if not parsed:
            break
        todays = [r for r in parsed if r.date == target]
        rows.extend(todays)
        if len(todays) < len(parsed) or len(parsed) < PAGE_SIZE:
            break
    return rows


async def _fill_excerpt(client: httpx.AsyncClient, sem: asyncio.Semaphore, r: ResearchReport) -> None:
    """상세 API의 content + PDF 앞부분으로 excerpt를 채운다. 실패는 스킵."""
    async with sem:
        path = CATEGORIES.get(r.category, "market")
        try:
            resp = await client.get(f"{API}/{path}/{r.research_id}", headers=HEADERS)
            resp.raise_for_status()
            content = (resp.json() or {}).get("researchContent") or {}
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:
            logger.warning("리포트 상세 실패, 스킵 (%s): %s", r.title, e)
            return
        parts: list[str] = []
        summary = html_to_text(content.get("content") or "")
        if summary:
            parts.append(summary)
        r.pdf_url = content.get("attachUrl") or None
        if r.pdf_url:
            try:
                pdf = await client.get(r.pdf_url, headers=HEADERS, timeout=30)
                pdf.raise_for_status()
                text = await asyncio.to_thread(extract_pdf_text, pdf.content)
                if text:
                    parts.append(text)
            except Exception as e:  # PDF 파싱 오류 포함
                logger.warning("PDF 실패, 요약만 사용 (%s): %s", r.title, e)
        r.excerpt = "\n\n".join(parts)[:EXCERPT_MAX_CHARS]


def _watch_codes() -> set[str]:
    return {t.split(".")[0] for t, _ in WATCHLIST if t.endswith((".KS", ".KQ"))}


async def collect_reports(
    target: date | None = None, categories: tuple[str, ...] | list[str] | None = None
) -> list[ResearchReport]:
    """당일 증권사 리포트를 수집해 발췌까지 채운 리스트를 반환한다. 실패는 축소.

    categories: 수집할 카테고리 표시명. 기본은 전체(CATEGORIES). 거시 전용은 MACRO_CATEGORIES.
    """
    target = target or datetime.now(_KST).date()
    cats = [c for c in (categories or CATEGORIES) if c in CATEGORIES]
    client = get_http_client()
    lists = await asyncio.gather(
        *[_fetch_list(client, c, target) for c in cats],
        return_exceptions=True,
    )
    watch = _watch_codes()
    selected: list[ResearchReport] = []
    counts: dict[str, int] = {}
    for category, rows in zip(cats, lists):
        if isinstance(rows, BaseException):
            logger.warning("리포트 목록 예외 (%s): %s", category, rows)
            continue
        if category == "종목":
            rows = [r for r in rows if r.ticker in watch]
        rows = sorted(rows, key=lambda r: r.views, reverse=True)[:PER_CATEGORY_LIMIT]
        counts[category] = len(rows)
        selected.extend(rows)
    selected = sorted(selected, key=lambda r: r.views, reverse=True)[:TOTAL_LIMIT]

    sem = asyncio.Semaphore(_CONCURRENCY)
    await asyncio.gather(*[_fill_excerpt(client, sem, r) for r in selected])
    result = [r for r in selected if r.excerpt]
    logger.info(
        "리포트 수집: %d건 (%s)",
        len(result),
        ", ".join(f"{k} {v}" for k, v in counts.items()),
    )
    return result
