"""네이버 증권 리서치 — 당일 증권사 리포트를 수집해 본문 발췌를 만든다.

소스: finance.naver.com/research/*_list.naver (비인증, EUC-KR).
시황·투자전략·산업·경제는 당일 전부, 종목분석은 WATCHLIST 종목만.
PDF가 있으면 앞 3페이지 텍스트, 없거나 실패하면 read 페이지 본문으로 폴백.
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

BASE = "https://finance.naver.com/research/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Referer": BASE}

# 카테고리 → 목록 페이지
CATEGORIES: dict[str, str] = {
    "시황": "market_info_list.naver",
    "투자전략": "invest_list.naver",
    "산업": "industry_list.naver",
    "경제": "economy_list.naver",
    "종목": "company_list.naver",
}

PER_CATEGORY_LIMIT = 15
TOTAL_LIMIT = 40
PDF_MAX_PAGES = 3
EXCERPT_MAX_CHARS = 6000
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


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", text)
    if not m:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    return date(2000 + yy, mm, dd)


def parse_list_page(html: str, category: str) -> list[ResearchReport]:
    """목록 페이지 HTML → ResearchReport 리스트 (excerpt 비어 있음)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="type_1")
    if table is None:
        return []
    out: list[ResearchReport] = []
    for tr in table.find_all("tr"):
        read_a = tr.find("a", href=re.compile(r"_read\.naver\?nid="))
        if read_a is None:
            continue
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        ticker = None
        stock_a = tr.find("a", class_="stock_item")
        if stock_a is not None:
            m = re.search(r"code=(\d{6})", stock_a.get("href", ""))
            ticker = m.group(1) if m else None
        # 증권사 셀: read 링크가 있는 td 바로 다음 td
        read_td = read_a.find_parent("td")
        broker_td = read_td.find_next_sibling("td") if read_td else None
        broker = broker_td.get_text(strip=True) if broker_td else ""
        file_td = tr.find("td", class_="file")
        pdf_a = file_td.find("a", href=re.compile(r"\.pdf$")) if file_td else None
        pdf_url = pdf_a["href"] if pdf_a else None
        date_tds = tr.find_all("td", class_="date")
        d = _parse_date(date_tds[0].get_text()) if date_tds else None
        if d is None:
            continue
        views = 0
        if len(date_tds) > 1:
            digits = re.sub(r"\D", "", date_tds[1].get_text())
            views = int(digits) if digits else 0
        out.append(
            ResearchReport(
                category=category,
                title=read_a.get_text(strip=True),
                broker=broker,
                date=d,
                ticker=ticker,
                pdf_url=pdf_url,
                read_url=BASE + read_a["href"].lstrip("/"),
                views=views,
            )
        )
    return out


def extract_read_text(html: str) -> str:
    """read 페이지의 본문(td.view_cnt) 텍스트를 뽑는다."""
    soup = BeautifulSoup(html, "html.parser")
    td = soup.find("td", class_="view_cnt")
    if td is None:
        return ""
    text = td.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf_text(data: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """PDF 앞 max_pages 페이지의 텍스트를 뽑는다."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts)
    return re.sub(r"[ \t]+", " ", text).strip()


def _decode(resp: httpx.Response) -> str:
    return resp.content.decode("euc-kr", errors="ignore")


async def _fetch_list(client: httpx.AsyncClient, category: str, target: date) -> list[ResearchReport]:
    """카테고리 목록을 당일 행이 끊길 때까지 페이지 순회한다."""
    rows: list[ResearchReport] = []
    for page in range(1, MAX_LIST_PAGES + 1):
        url = f"{BASE}{CATEGORIES[category]}?page={page}"
        try:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            logger.warning("리포트 목록 실패 (%s p%d): %s", category, page, e)
            break
        parsed = parse_list_page(_decode(resp), category)
        if not parsed:
            break
        todays = [r for r in parsed if r.date == target]
        rows.extend(todays)
        if len(todays) < len(parsed) or any(r.date < target for r in parsed):
            break
    return rows


async def _fill_excerpt(client: httpx.AsyncClient, sem: asyncio.Semaphore, r: ResearchReport) -> None:
    async with sem:
        if r.pdf_url:
            try:
                resp = await client.get(r.pdf_url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                text = await asyncio.to_thread(extract_pdf_text, resp.content)
                if text:
                    r.excerpt = text[:EXCERPT_MAX_CHARS]
                    return
            except Exception as e:  # PDF 파싱 오류 포함
                logger.warning("PDF 실패 → read 폴백 (%s): %s", r.title, e)
        try:
            resp = await client.get(r.read_url, headers=HEADERS)
            resp.raise_for_status()
            r.excerpt = extract_read_text(_decode(resp))[:EXCERPT_MAX_CHARS]
        except Exception as e:
            logger.warning("read 페이지 실패, 스킵 (%s): %s", r.title, e)


def _watch_codes() -> set[str]:
    return {t.split(".")[0] for t, _ in WATCHLIST if t.endswith((".KS", ".KQ"))}


async def collect_reports(target: date | None = None) -> list[ResearchReport]:
    """당일 증권사 리포트를 수집해 발췌까지 채운 리스트를 반환한다. 실패는 축소."""
    target = target or datetime.now(_KST).date()
    client = get_http_client()
    lists = await asyncio.gather(
        *[_fetch_list(client, c, target) for c in CATEGORIES],
        return_exceptions=True,
    )
    watch = _watch_codes()
    selected: list[ResearchReport] = []
    counts: dict[str, int] = {}
    for category, rows in zip(CATEGORIES, lists):
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
