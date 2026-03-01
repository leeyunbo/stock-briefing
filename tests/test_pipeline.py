"""파이프라인 테스트."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.collector.dart import Disclosure
from app.collector.market import MarketSummary, IndexData
from app.collector.news import NewsArticle
from app.core.database import Base
from app.core.models import Briefing
from app.pipeline.base import BriefingResult, save_briefing
from app.pipeline.kospi import CollectedData, collect_data, summarize, _is_market_closed_yesterday, _filter_disclosures, _DISCLOSURE_FALLBACK_COUNT
from tests.db_setup import TestSession, engine as test_engine


@pytest.mark.asyncio
async def test_collect_data():
    """collect_data가 3개 수집기를 병렬 호출하고 결과를 합친다."""
    fake_market = MarketSummary(
        date=(date.today() - timedelta(days=1)).isoformat(),
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=None,
        kospi_top10=[],
    )

    with (
        patch("app.pipeline.kospi.fetch_market_summary", new_callable=AsyncMock, return_value=fake_market),
        patch("app.pipeline.kospi.fetch_disclosures", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.kospi.fetch_stock_news", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.kospi.fetch_news_for_stocks", new_callable=AsyncMock, return_value={}),
    ):
        data = await collect_data()

    assert isinstance(data, CollectedData)
    assert data.market.kospi.name == "코스피"


def test_summarize():
    """summarize가 CollectedData를 받아 BriefingResult를 반환한다."""
    data = CollectedData(
        market=MarketSummary(
            date=(date.today() - timedelta(days=1)).isoformat(),
            kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
            kosdaq=None,
            kospi_top10=[],
        ),
        disclosures=[],
        news=[],
    )

    from app.summarizer import SeoMetadata
    fake_seo = SeoMetadata(html="<h2>요약</h2>")
    with patch("app.pipeline.kospi.generate_briefing", return_value=fake_seo):
        result = summarize(data)

    assert isinstance(result, BriefingResult)
    assert "요약" in result.html
    assert "브리핑" in result.title


@pytest.mark.asyncio
async def test_save_briefing_creates_new(db_session):
    """save_briefing이 새 브리핑을 DB에 저장한다."""
    result = BriefingResult(title="테스트 브리핑", html="<h2>내용</h2>")

    with patch("app.pipeline.base.async_session", TestSession):
        await save_briefing(result)

    async with TestSession() as session:
        row = await session.execute(select(Briefing).where(Briefing.date == date.today()))
        briefing = row.scalar_one_or_none()
        assert briefing is not None
        assert briefing.title == "테스트 브리핑"


@pytest.mark.asyncio
async def test_collect_data_partial_failure():
    """수집기 일부 실패 시에도 나머지 결과를 반환한다."""
    fake_market = MarketSummary(
        date=(date.today() - timedelta(days=1)).isoformat(),
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=None,
        kospi_top10=[],
    )

    with (
        patch("app.pipeline.kospi.fetch_market_summary", new_callable=AsyncMock, return_value=fake_market),
        patch("app.pipeline.kospi.fetch_disclosures", new_callable=AsyncMock, side_effect=Exception("DART 에러")),
        patch("app.pipeline.kospi.fetch_stock_news", new_callable=AsyncMock, return_value=[]),
        patch("app.pipeline.kospi.fetch_news_for_stocks", new_callable=AsyncMock, return_value={}),
    ):
        data = await collect_data()

    assert isinstance(data, CollectedData)
    assert data.market.kospi.name == "코스피"
    assert data.disclosures == []  # 실패한 수집기는 빈 결과


# ── 휴장일 감지 테스트 ──


def test_is_market_closed_yesterday_normal():
    """전날 날짜면 정상 거래일로 판단한다."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert _is_market_closed_yesterday(yesterday) is False


def test_is_market_closed_yesterday_closed():
    """이틀 전 날짜면 휴장으로 판단한다."""
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    assert _is_market_closed_yesterday(two_days_ago) is True


def test_is_market_closed_yesterday_empty():
    """빈 문자열이면 False를 반환한다."""
    assert _is_market_closed_yesterday("") is False


@pytest.mark.asyncio
async def test_collect_data_market_closed():
    """휴장일이면 공시/종목뉴스를 스킵하고 뉴스만 수집한다."""
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    fake_market = MarketSummary(
        date=two_days_ago,
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=None,
        kospi_top10=[],
    )
    fake_news = [NewsArticle(title="테스트 뉴스", description="설명", link="http://example.com", pub_date="2025-01-01")]

    with (
        patch("app.pipeline.kospi.fetch_market_summary", new_callable=AsyncMock, return_value=fake_market),
        patch("app.pipeline.kospi.fetch_disclosures", new_callable=AsyncMock) as mock_disc,
        patch("app.pipeline.kospi.fetch_stock_news", new_callable=AsyncMock, return_value=fake_news),
        patch("app.pipeline.kospi.fetch_news_for_stocks", new_callable=AsyncMock) as mock_stock_news,
    ):
        data = await collect_data()

    assert data.is_market_closed is True
    assert data.disclosures == []
    assert len(data.news) == 1
    mock_disc.assert_not_called()
    mock_stock_news.assert_not_called()


# ── 공시 키워드 필터링 테스트 ──


def _make_disclosure(report_nm: str, corp_name: str = "테스트") -> Disclosure:
    return Disclosure(corp_name=corp_name, report_nm=report_nm, rcept_dt="20250101", rcept_no="0001", flr_nm="대표")


def test_filter_disclosures_keyword_match():
    """키워드가 포함된 공시만 필터링한다."""
    disclosures = [
        _make_disclosure("자기주식 취득 결정"),
        _make_disclosure("사업보고서 (2024.12)"),
        _make_disclosure("유상증자 결정"),
        _make_disclosure("감사보고서 제출"),
    ]
    result = _filter_disclosures(disclosures)
    assert len(result) == 2
    assert result[0].report_nm == "자기주식 취득 결정"
    assert result[1].report_nm == "유상증자 결정"


def test_filter_disclosures_no_match_fallback():
    """키워드 매칭이 없으면 상위 N건을 반환한다."""
    disclosures = [_make_disclosure(f"사업보고서 ({i})") for i in range(10)]
    result = _filter_disclosures(disclosures)
    assert len(result) == _DISCLOSURE_FALLBACK_COUNT


def test_filter_disclosures_empty():
    """빈 리스트는 그대로 반환한다."""
    assert _filter_disclosures([]) == []
