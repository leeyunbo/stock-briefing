"""파이프라인 테스트."""

from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.collector.dart import Disclosure
from app.collector.market import MarketSummary, IndexData
from app.collector.news import NewsArticle
from app.database import Base
from app.models import Briefing
from app.pipeline import CollectedData, BriefingResult, collect_data, summarize, save_briefing


# ── 테스트용 DB 설정 ──

TEST_DB_URL = "sqlite+aiosqlite://"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


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


@pytest.mark.asyncio
async def test_save_briefing_creates_new():
    """save_briefing이 새 브리핑을 DB에 저장한다."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = BriefingResult(title="테스트 브리핑", html="<h2>내용</h2>")

    with patch("app.pipeline.async_session", TestSession):
        await save_briefing(result)

    async with TestSession() as session:
        row = await session.execute(select(Briefing).where(Briefing.date == date.today()))
        briefing = row.scalar_one_or_none()
        assert briefing is not None
        assert briefing.title == "테스트 브리핑"

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_collect_data_partial_failure():
    """수집기 일부 실패 시에도 나머지 결과를 반환한다."""
    fake_market = MarketSummary(
        date="2025-02-11",
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=None,
        kospi_top10=[],
    )

    with (
        patch("app.pipeline.fetch_market_summary", new_callable=AsyncMock, return_value=fake_market),
        patch("app.pipeline.fetch_disclosures", new_callable=AsyncMock, side_effect=Exception("DART 에러")),
        patch("app.pipeline.fetch_stock_news", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.fetch_news_for_stocks", new_callable=AsyncMock, return_value={}),
    ):
        data = await collect_data()

    assert isinstance(data, CollectedData)
    assert data.market.kospi.name == "코스피"
    assert data.disclosures == []  # 실패한 수집기는 빈 결과
