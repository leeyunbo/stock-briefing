"""나스닥/부동산/뉴스 딥다이브 파이프라인 테스트."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.collector.nasdaq import NasdaqSummary, USIndexData, USStockData
from app.collector.real_estate import RealEstateData, RealEstateNews
from app.pipeline.base import BriefingResult, run_steps


# ── run_steps 테스트 ──


@pytest.mark.asyncio
async def test_run_steps_executes_all():
    """모든 스텝이 순서대로 실행된다."""
    order = []

    async def step_a(ctx):
        order.append("a")

    async def step_b(ctx):
        order.append("b")

    ctx = {}
    await run_steps([step_a, step_b], ctx)
    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_run_steps_skip():
    """skip=True 설정 시 이후 스텝은 실행되지 않는다."""
    order = []

    async def step_a(ctx):
        order.append("a")
        ctx["skip"] = True

    async def step_b(ctx):
        order.append("b")

    ctx = {}
    await run_steps([step_a, step_b], ctx)
    assert order == ["a"]
    assert ctx.get("skip") is True


# ── 나스닥 파이프라인 ──


@pytest.mark.asyncio
async def test_collect_nasdaq_data():
    """나스닥 수집 스텝이 NasdaqCollectedData를 ctx에 저장한다."""
    from app.pipeline.nasdaq import collect_nasdaq_data

    fake_summary = NasdaqSummary(
        date="2026-03-01",
        indices=[USIndexData(name="나스닥 100", close="520", change="+2", change_pct="+0.4", direction="상승")],
    )

    with (
        patch("app.pipeline.nasdaq.fetch_nasdaq_summary", new_callable=AsyncMock, return_value=fake_summary),
        patch("app.pipeline.nasdaq.save_nasdaq_snapshot", new_callable=AsyncMock),
        patch("app.pipeline.nasdaq.fetch_index_history", new_callable=AsyncMock, return_value=[]),
    ):
        ctx = {"run_id": "test123", "pipeline": "nasdaq"}
        await collect_nasdaq_data(ctx)

    assert "collected" in ctx
    assert ctx["collected"].summary.date == "2026-03-01"
    assert len(ctx["collected"].summary.indices) == 1


@pytest.mark.asyncio
async def test_summarize_nasdaq():
    """나스닥 요약 스텝이 BriefingResult를 ctx에 저장한다."""
    from app.pipeline.nasdaq import summarize_nasdaq, NasdaqCollectedData

    fake_collected = NasdaqCollectedData(
        summary=NasdaqSummary(
            date="2026-03-01",
            indices=[USIndexData(name="나스닥 100", close="520", change="+2", change_pct="+0.4", direction="상승")],
        ),
    )

    fake_result = BriefingResult(title="나스닥 브리핑", html="<h2>내용</h2>")

    with patch("app.prompts.nasdaq.summarize_nasdaq_data", return_value=fake_result):
        ctx = {"run_id": "test456", "pipeline": "nasdaq", "collected": fake_collected}
        await summarize_nasdaq(ctx)

    assert ctx["result"].title == "나스닥 브리핑"


# ── 부동산 파이프라인 ──


@pytest.mark.asyncio
async def test_collect_real_estate_data():
    """부동산 수집 스텝이 뉴스와 청약 데이터를 ctx에 저장한다."""
    from app.pipeline.real_estate import collect_real_estate_data

    fake_news = [RealEstateNews(title="부동산 뉴스", summary="설명", link="http://ex.com", pub_date="2026-03-01")]

    with (
        patch("app.pipeline.real_estate.fetch_real_estate_news", new_callable=AsyncMock, return_value=fake_news),
        patch("app.pipeline.real_estate.fetch_all_subscription_data", new_callable=AsyncMock, return_value=([], {})),
    ):
        ctx = {"run_id": "test789", "pipeline": "real_estate"}
        await collect_real_estate_data(ctx)

    assert len(ctx["news"]) == 1
    assert ctx["news"][0].title == "부동산 뉴스"


@pytest.mark.asyncio
async def test_generate_re_report():
    """부동산 리포트 스텝이 BriefingResult를 ctx에 저장한다."""
    from app.pipeline.real_estate import generate_re_report

    fake_result = BriefingResult(title="부동산 브리핑", html="<h2>내용</h2>")

    with patch("app.pipeline.real_estate.generate_real_estate_report", return_value=fake_result):
        ctx = {
            "run_id": "testabc",
            "pipeline": "real_estate",
            "news": [],
            "subscriptions": [],
            "prices": {},
        }
        await generate_re_report(ctx)

    assert ctx["result"].title == "부동산 브리핑"


# ── 뉴스 딥다이브 파이프라인 ──


@pytest.mark.asyncio
async def test_collect_market_data():
    """뉴스 딥다이브 수집 스텝이 scan과 macro를 ctx에 저장한다."""
    from app.pipeline.research import collect_market_data
    from app.collector.research_models import MarketScanData, MacroIndicators

    fake_scan = MarketScanData(scan_date="2026-03-01")
    fake_macro = MacroIndicators()

    with (
        patch("app.pipeline.research.scan_market", new_callable=AsyncMock, return_value=fake_scan),
        patch("app.pipeline.research.fetch_macro_indicators", new_callable=AsyncMock, return_value=fake_macro),
    ):
        ctx = {"run_id": "testdef", "pipeline": "news_dive"}
        await collect_market_data(ctx)

    assert "scan" in ctx
    assert "macro" in ctx
    assert ctx["scan"].scan_date == "2026-03-01"


def test_extract_mentioned_tickers():
    """뉴스 분석에서 중복 없이 티커를 추출한다."""
    from app.pipeline.research import _extract_mentioned_tickers

    analysis = {
        "stories": [
            {"affected_tickers": ["AAPL", "NVDA"], "beneficiary_tickers": ["MSFT"]},
            {"affected_tickers": ["AAPL"], "beneficiary_tickers": ["GOOGL"]},
        ]
    }
    tickers = _extract_mentioned_tickers(analysis)
    assert tickers == ["AAPL", "NVDA", "MSFT", "GOOGL"]
