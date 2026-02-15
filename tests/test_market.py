"""시장 데이터 수집기 테스트."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.collector.market import MarketSummary, fetch_market_summary


@pytest.mark.asyncio
async def test_fetch_market_summary_success():
    """정상 응답 시 MarketSummary를 반환한다."""
    index_json = {
        "stockName": "코스피",
        "closePrice": "2500",
        "compareToPreviousClosePrice": "30",
        "fluctuationsRatio": "1.2",
        "compareToPreviousPrice": {"text": "상승"},
        "localTradedAt": "2025-02-11T15:30",
    }
    top10_json = {"stocks": []}
    trend_json = {
        "personalValue": "1000",
        "foreignValue": "-500",
        "institutionalValue": "-500",
    }

    async def fake_get(url, **kwargs):
        if "/basic" in url:
            return httpx.Response(200, json=index_json, request=httpx.Request("GET", url))
        if "/marketValue" in url:
            return httpx.Response(200, json=top10_json, request=httpx.Request("GET", url))
        if "/trend" in url:
            return httpx.Response(200, json=trend_json, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("app.collector.market.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get = fake_get
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_market_summary()

    assert isinstance(result, MarketSummary)
    assert result.kospi is not None
    assert result.kospi.name == "코스피"


@pytest.mark.asyncio
async def test_fetch_market_summary_all_fail():
    """모든 API 호출 실패 시 빈 MarketSummary를 반환한다."""
    with patch("app.collector.market.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.ConnectError("연결 실패")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_market_summary()

    assert isinstance(result, MarketSummary)
    assert result.kospi is None
    assert result.kosdaq is None
    assert result.kospi_top10 == []
