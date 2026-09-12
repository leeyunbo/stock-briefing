"""네이버 증권사 리포트 수집기 테스트 (m.stock.naver.com JSON API)."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.collector.naver_research import (
    ResearchReport,
    collect_reports,
    html_to_text,
    parse_list,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_market_list_rows():
    rows = parse_list(_load("naver_api_market_list.json"), "시황")
    assert rows and all(isinstance(r, ResearchReport) for r in rows)
    r = rows[0]
    assert r.research_id == "37468"
    assert r.broker == "신한투자증권"
    assert r.date == date(2026, 9, 10)
    assert r.ticker is None
    assert r.pdf_url is None  # 상세에서 채움
    assert r.read_url == "https://m.stock.naver.com/research/market/37468"
    assert r.views > 0
    assert r.category == "시황" and r.excerpt == ""


def test_parse_company_list_has_ticker():
    rows = parse_list(_load("naver_api_company_list.json"), "종목")
    assert rows
    assert rows[0].ticker == "195940" and rows[0].title == "여전히 주가의 원동력은 케이캡"


def test_parse_garbage_returns_empty():
    assert parse_list([{"foo": 1}, "x", None], "시황") == []
    assert parse_list([], "시황") == []


def test_html_to_text_strips_tags_and_nbsp():
    html = "<p><strong>KOSPI 1.6% 하락</strong></p><p>&nbsp;</p><p>둘째</p>"
    assert html_to_text(html) == "KOSPI 1.6% 하락 둘째"
    assert html_to_text("") == ""


def _resp(payload, url: str, content: bytes | None = None) -> httpx.Response:
    req = httpx.Request("GET", url)
    if content is not None:
        return httpx.Response(200, content=content, request=req)
    return httpx.Response(200, json=payload, request=req)


def _client(handler):
    client = AsyncMock()
    client.get.side_effect = handler
    return client


@pytest.mark.asyncio
async def test_collect_reports_filters_date_watchlist_and_fills_excerpt():
    """당일 필터 + 종목 WATCHLIST 필터 + 상세 content/PDF 결합을 검증한다."""
    market = _load("naver_api_market_list.json")
    company = _load("naver_api_company_list.json")
    market_detail = _load("naver_api_market_detail.json")
    company_detail = _load("naver_api_company_detail.json")

    async def fake_get(url, **kw):
        if url.endswith(".pdf"):
            raise httpx.ConnectError("pdf down")  # PDF 실패 → 요약만
        if "/research/company?" in url:
            return _resp(company, url)
        if "/research/company/" in url:
            return _resp(company_detail, url)
        if "?page=" in url:
            return _resp(market, url)
        return _resp(market_detail, url)

    with patch("app.collector.naver_research.get_http_client", return_value=_client(fake_get)), \
         patch("app.collector.naver_research.WATCHLIST", [("195940.KS", "HK이노엔")]):
        rows = await collect_reports(target=date(2026, 9, 10))

    assert rows
    assert all(r.date == date(2026, 9, 10) for r in rows)
    company_rows = [r for r in rows if r.category == "종목"]
    assert {r.ticker for r in company_rows} == {"195940"}
    market_rows = [r for r in rows if r.category == "시황"]
    assert market_rows and "KOSPI는 1.6% 하락" in market_rows[0].excerpt
    assert market_rows[0].pdf_url.endswith(".pdf")  # 상세에서 채워짐
    assert "케이캡" in company_rows[0].excerpt


@pytest.mark.asyncio
async def test_collect_reports_appends_pdf_text():
    market = _load("naver_api_market_list.json")[:1]
    detail = _load("naver_api_market_detail.json")

    async def fake_get(url, **kw):
        if url.endswith(".pdf"):
            return _resp(None, url, content=b"%PDF")
        if "?page=" in url:
            return _resp(market if "/market?" in url else [], url)
        return _resp(detail, url)

    with patch("app.collector.naver_research.get_http_client", return_value=_client(fake_get)), \
         patch("app.collector.naver_research.extract_pdf_text", return_value="PDF 본문 텍스트"):
        rows = await collect_reports(target=date(2026, 9, 10))
    assert len(rows) == 1
    assert rows[0].excerpt.endswith("PDF 본문 텍스트") and "KOSPI" in rows[0].excerpt


@pytest.mark.asyncio
async def test_collect_reports_no_match_date():
    market = _load("naver_api_market_list.json")

    async def fake_get(url, **kw):
        return _resp(market, url)

    with patch("app.collector.naver_research.get_http_client", return_value=_client(fake_get)):
        rows = await collect_reports(target=date(2020, 1, 1))
    assert rows == []


@pytest.mark.asyncio
async def test_collect_reports_network_error_returns_empty():
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("down")
    with patch("app.collector.naver_research.get_http_client", return_value=client):
        rows = await collect_reports(target=date(2026, 9, 10))
    assert rows == []


@pytest.mark.asyncio
async def test_collect_reports_detail_failure_skips_row():
    market = _load("naver_api_market_list.json")[:2]

    async def fake_get(url, **kw):
        if "?page=" in url:
            return _resp(market if "/market?" in url else [], url)
        raise httpx.ConnectError("detail down")

    with patch("app.collector.naver_research.get_http_client", return_value=_client(fake_get)):
        rows = await collect_reports(target=date(2026, 9, 10))
    assert rows == []


@pytest.mark.asyncio
async def test_collect_reports_categories_filter_skips_company():
    market = _load("naver_api_market_list.json")[:1]
    detail = _load("naver_api_market_detail.json")
    seen = []

    async def fake_get(url, **kw):
        seen.append(url)
        if url.endswith(".pdf"):
            raise httpx.ConnectError("no pdf")
        if "?page=" in url:
            return _resp(market if "/market?" in url else [], url)
        return _resp(detail, url)

    from app.collector.naver_research import MACRO_CATEGORIES
    with patch("app.collector.naver_research.get_http_client", return_value=_client(fake_get)):
        rows = await collect_reports(target=date(2026, 9, 10), categories=MACRO_CATEGORIES)
    assert len(rows) == 1
    assert not any("/research/company" in u for u in seen)
