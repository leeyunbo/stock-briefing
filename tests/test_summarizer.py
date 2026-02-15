"""요약기 테스트 — Protocol/Strategy 패턴 검증.

스프링 대응:
- mock provider = @MockBean AiProvider
- _strip_code_block 테스트 = 순수 유틸 단위 테스트
"""

from unittest.mock import patch

import pytest

from app.collector.dart import Disclosure
from app.collector.market import MarketSummary, IndexData, StockData
from app.collector.news import NewsArticle
from app.summarizer import _strip_code_block, generate_briefing


# ── 순수 함수 테스트 ──


def test_strip_code_block_removes_markers():
    """```html ... ``` 코드블록 마커를 제거한다."""
    raw = "```html\n<h1>제목</h1>\n```"
    assert _strip_code_block(raw) == "<h1>제목</h1>"


def test_strip_code_block_plain_text():
    """마커 없는 텍스트는 그대로 반환한다."""
    assert _strip_code_block("<h1>제목</h1>") == "<h1>제목</h1>"


# ── AI 호출을 Mock한 통합 테스트 ──


@pytest.mark.asyncio
async def test_generate_briefing_calls_provider():
    """generate_briefing이 provider.call()을 호출하고 결과를 반환한다."""
    market = MarketSummary(
        date="2025-02-11",
        kospi=IndexData(name="코스피", close="2,500", change="30", change_pct="1.2", direction="상승"),
        kosdaq=IndexData(name="코스닥", close="700", change="-5", change_pct="-0.7", direction="하락"),
        kospi_top10=[],
    )
    disclosures = [
        Disclosure(corp_name="삼성전자", report_nm="사업보고서", rcept_dt="20250211", rcept_no="12345", flr_nm="삼성전자"),
    ]
    news = [
        NewsArticle(title="증시 상승", description="코스피 올랐다", link="https://ex.com", pub_date="Mon"),
    ]

    # _get_provider()를 mock해서 실제 AI API를 호출하지 않는다
    fake_provider_instance = type("FakeProvider", (), {"call": lambda self, s, u: "<h2>테스트 브리핑</h2>"})()

    with patch("app.summarizer._get_provider", return_value=fake_provider_instance):
        result = generate_briefing(market, disclosures, news)

    assert "<h2>테스트 브리핑</h2>" in result
