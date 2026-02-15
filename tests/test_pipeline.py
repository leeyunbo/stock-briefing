"""파이프라인 테스트 — 각 단계를 Mock으로 격리.

스프링 대응:
- patch() = @MockBean (서비스 계층 교체)
- CollectedData/BriefingResult = 테스트용 DTO 직접 생성
"""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.collector.dart import Disclosure
from app.collector.market import MarketSummary, IndexData
from app.collector.news import NewsArticle
from app.pipeline import CollectedData, BriefingResult, collect_data, summarize


@pytest.mark.asyncio
async def test_collect_data():
    """collect_data가 3개 수집기를 병렬 호출하고 결과를 합친다."""
    fake_market = MarketSummary(
        date="2025-02-11",
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=None,
        kospi_top10=[],
    )

    with (
        patch("app.pipeline.fetch_market_summary", new_callable=AsyncMock, return_value=fake_market),
        patch("app.pipeline.fetch_disclosures", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.fetch_stock_news", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.fetch_news_for_stocks", new_callable=AsyncMock, return_value={}),
    ):
        data = await collect_data()

    assert isinstance(data, CollectedData)
    assert data.market.kospi.name == "코스피"


def test_summarize():
    """summarize가 CollectedData를 받아 BriefingResult를 반환한다."""
    data = CollectedData(
        market=MarketSummary(
            date="2025-02-11",
            kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
            kosdaq=None,
            kospi_top10=[],
        ),
        disclosures=[],
        news=[],
    )

    with patch("app.pipeline.generate_briefing", return_value="<h2>요약</h2>"):
        result = summarize(data)

    assert isinstance(result, BriefingResult)
    assert "요약" in result.html
    assert "브리핑" in result.title
