"""개인 아침 브리핑 — 스포트라이트 종목 심층 데이터 수집.

핫 종목 1~2개에 대해 재무(US/KR 딥리서치) + 기술적 지표 + 차트 PNG를 모은다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from dataclasses import dataclass, field

from app.collector.technical import (
    TechnicalIndicators,
    calculate_indicators,
    fetch_ohlcv_kr,
    fetch_ohlcv_us,
)

logger = logging.getLogger(__name__)


@dataclass
class SpotlightData:
    """스포트라이트 종목의 심층 데이터."""

    ticker: str
    name: str
    market: str  # "US" / "KR"
    indicators: TechnicalIndicators | None = None
    financials: dict = field(default_factory=dict)
    chart_png: bytes | None = None


def _is_kr(ticker: str) -> bool:
    return ticker.endswith(".KS") or ticker.endswith(".KQ")


def _compact_us(d) -> dict:
    """US 딥리서치에서 프롬프트에 넣을 핵심만 추린다."""
    return {
        "profile": d.profile.model_dump(),
        "quote": d.quote.model_dump(),
        "financials": d.financials.model_dump(),
        "recommendations": [r.model_dump() for r in d.recommendations[:2]],
        "earnings": [e.model_dump() for e in d.earnings[:4]],
        "news": [n.model_dump() for n in d.news[:5]],
    }


def _compact_kr(d) -> dict:
    return {
        "profile": d.profile.model_dump(),
        "quote": d.quote.model_dump(),
        "financials": [f.model_dump() for f in d.financials[:4]],
        "news": d.news_headlines[:5],
    }


async def fetch_spotlight(ticker: str, name: str) -> SpotlightData:
    """종목 1개의 재무 + 기술지표 + 차트를 수집한다. 부분 실패는 무시."""
    kr = _is_kr(ticker)
    market = "KR" if kr else "US"
    code = ticker.split(".")[0] if kr else ticker

    sp = SpotlightData(ticker=ticker, name=name, market=market)

    # 기술적 지표 + 차트
    try:
        df = await fetch_ohlcv_kr(code) if kr else await to_thread(fetch_ohlcv_us, ticker)
        ind = calculate_indicators(df, ticker, market)
        ind.name = name
        sp.indicators = ind
        from app.publishing.ta_chart import render_price_chart
        sp.chart_png = await to_thread(render_price_chart, ind)
    except Exception as e:
        logger.warning("기술 분석/차트 실패 (%s): %s", ticker, e)

    # 재무 딥리서치
    try:
        if kr:
            from app.collector.kr_stock_research import fetch_kr_stock_research
            sp.financials = _compact_kr(await fetch_kr_stock_research(code))
        else:
            from app.collector.stock_research import fetch_stock_research
            sp.financials = _compact_us(await fetch_stock_research(ticker))
    except Exception as e:
        logger.warning("재무 수집 실패 (%s): %s", ticker, e)

    return sp
