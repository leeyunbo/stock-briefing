"""뉴스 수집기 테스트.

스프링 대응:
- @MockBean WebClient → unittest.mock.patch("httpx.AsyncClient")
- assertThat().isEqualTo() → assert == (pytest는 assert 하나로 다 한다)
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.collector.news import NewsArticle, _strip_html, fetch_news


# ── 순수 함수 테스트 (Mockito 필요 없음) ──


def test_strip_html_removes_tags():
    """HTML 태그가 제거된다."""
    assert _strip_html("<b>삼성전자</b> 급등") == "삼성전자 급등"


def test_strip_html_unescapes_entities():
    """HTML 엔티티가 원래 문자로 변환된다."""
    assert _strip_html("A &amp; B &lt;C&gt;") == "A & B <C>"


# ── 비동기 API 호출 테스트 (Mock 사용) ──


@pytest.mark.asyncio
async def test_fetch_news_success():
    """정상 응답 시 NewsArticle 리스트를 반환한다."""
    fake_response = httpx.Response(
        200,
        json={
            "items": [
                {
                    "title": "<b>삼성전자</b> 실적 발표",
                    "description": "영업이익 12조",
                    "originallink": "https://example.com/1",
                    "pubDate": "Mon, 10 Feb 2025",
                },
            ]
        },
        request=httpx.Request("GET", "https://test.com"),
    )

    # patch: httpx.AsyncClient.get을 가짜로 교체
    # 스프링의 @MockBean + when(webClient.get()).thenReturn() 과 같다
    with patch("app.collector.news.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = fake_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_news(query="삼성전자", count=1)

    assert len(result) == 1
    assert isinstance(result[0], NewsArticle)
    assert result[0].title == "삼성전자 실적 발표"  # HTML 태그 제거됨


@pytest.mark.asyncio
async def test_fetch_news_http_error_returns_empty():
    """HTTP 에러 시 빈 리스트를 반환한다 (graceful degradation)."""
    fake_response = httpx.Response(
        500,
        request=httpx.Request("GET", "https://test.com"),
    )

    with patch("app.collector.news.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.return_value = fake_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_news(query="테스트")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_news_network_error_returns_empty():
    """네트워크 에러 시 빈 리스트를 반환한다."""
    with patch("app.collector.news.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get.side_effect = httpx.ConnectError("연결 실패")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_news(query="테스트")

    assert result == []
