"""네이버 증권사 리포트 수집기 테스트."""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.collector.naver_research import (
    ResearchReport,
    collect_reports,
    extract_read_text,
    parse_list_page,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIX / name).read_bytes().decode("euc-kr", errors="ignore")


def test_parse_market_list_rows():
    rows = parse_list_page(_load("naver_market_list.html"), "시황")
    assert rows and all(isinstance(r, ResearchReport) for r in rows)
    r = next(r for r in rows if r.broker == "SK증권")
    assert r.pdf_url.endswith(".pdf")
    assert r.date == date(2026, 9, 9)
    assert r.ticker is None
    assert r.read_url.startswith("https://finance.naver.com/research/market_info_read.naver?nid=")
    assert r.views > 0
    assert r.category == "시황"
    assert r.excerpt == ""


def test_parse_row_without_pdf():
    rows = parse_list_page(_load("naver_market_list.html"), "시황")
    assert any(r.pdf_url is None for r in rows)


def test_parse_company_list_has_ticker():
    rows = parse_list_page(_load("naver_company_list.html"), "종목")
    assert rows
    assert rows[0].ticker and len(rows[0].ticker) == 6
    assert rows[0].read_url.startswith("https://finance.naver.com/research/company_read.naver?nid=")


def test_parse_garbage_returns_empty():
    assert parse_list_page("<html><body>nothing</body></html>", "시황") == []


def test_extract_read_text_strips_tags():
    html = '<table><tr><td colspan="2" class="view_cnt"><p>안녕 <b>세계</b></p>둘</td></tr></table>'
    assert extract_read_text(html) == "안녕 세계 둘"


def test_extract_read_text_missing_returns_empty():
    assert extract_read_text("<html></html>") == ""


def _resp(content: bytes, url: str) -> httpx.Response:
    return httpx.Response(200, content=content, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_collect_reports_filters_date_watchlist_and_fills_excerpt():
    """당일 필터 + 종목 WATCHLIST 필터 + read 페이지 폴백을 검증한다."""
    market_html = _load("naver_market_list.html").encode("euc-kr", errors="ignore")
    company_html = _load("naver_company_list.html").encode("euc-kr", errors="ignore")
    read_html = '<td colspan="2" class="view_cnt">본문입니다</td>'.encode("euc-kr")

    async def fake_get(url, **kw):
        if "company_list" in url:
            return _resp(company_html, url)
        if "_list.naver" in url:
            return _resp(market_html, url)
        if url.endswith(".pdf"):
            raise httpx.ConnectError("pdf down")
        return _resp(read_html, url)

    client = AsyncMock()
    client.get.side_effect = fake_get
    with patch("app.collector.naver_research.get_http_client", return_value=client), \
         patch("app.collector.naver_research.WATCHLIST", [("012630.KS", "HDC")]):
        rows = await collect_reports(target=date(2026, 9, 9))

    assert rows
    assert all(r.date == date(2026, 9, 9) for r in rows)
    company = [r for r in rows if r.category == "종목"]
    assert {r.ticker for r in company} == {"012630"}
    # PDF 실패 → read 페이지 폴백
    assert all(r.excerpt == "본문입니다" for r in rows)


@pytest.mark.asyncio
async def test_collect_reports_no_match_date():
    market_html = _load("naver_market_list.html").encode("euc-kr", errors="ignore")
    client = AsyncMock()
    client.get.return_value = _resp(market_html, "https://x")
    with patch("app.collector.naver_research.get_http_client", return_value=client):
        rows = await collect_reports(target=date(2020, 1, 1))
    assert rows == []


@pytest.mark.asyncio
async def test_collect_reports_network_error_returns_empty():
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("down")
    with patch("app.collector.naver_research.get_http_client", return_value=client):
        rows = await collect_reports(target=date(2026, 9, 9))
    assert rows == []
