"""DART 수집기 테스트."""

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.collector.dart import Disclosure, fetch_disclosures


@pytest.mark.asyncio
async def test_fetch_disclosures_success():
    """정상 응답 시 Disclosure 리스트를 반환한다."""
    fake_data = {
        "status": "000",
        "list": [
            {
                "corp_name": "삼성전자",
                "report_nm": "사업보고서",
                "rcept_dt": "20250211",
                "rcept_no": "00001",
                "flr_nm": "삼성전자",
            },
        ],
    }
    fake_response = httpx.Response(
        200,
        json=fake_data,
        request=httpx.Request("GET", "https://test.com"),
    )

    with patch("app.collector.dart.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = fake_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_disclosures(target_date=date(2025, 2, 11))

    assert len(result) >= 1
    assert isinstance(result[0], Disclosure)
    assert result[0].corp_name == "삼성전자"


@pytest.mark.asyncio
async def test_fetch_disclosures_network_error():
    """네트워크 에러 시 빈 리스트를 반환한다."""
    with patch("app.collector.dart.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.ConnectError("연결 실패")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_disclosures(target_date=date(2025, 2, 11))

    assert result == []
