"""나스닥 데이터 수집기 — Finnhub API로 미국 주요 지수(ETF 프록시) 및 워치리스트 종목 데이터를 수집한다.

Finnhub 무료 티어는 지수 직접 조회 불가 → ETF 프록시 사용:
- QQQ → 나스닥 100, SPY → S&P 500, DIA → 다우존스
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


# ── Pydantic 모델 ──


class USIndexData(BaseModel):
    """미국 지수 데이터 (ETF 프록시 기반)."""

    name: str
    close: str
    change: str
    change_pct: str
    direction: str


class USStockData(BaseModel):
    """미국 개별 종목 데이터."""

    ticker: str
    name: str
    close: str
    change_pct: str
    direction: str
    market_cap: str
    news: list[str] = []


class NasdaqSummary(BaseModel):
    """나스닥 수집 데이터 최상위 모델."""

    date: str = ""
    indices: list[USIndexData] = []
    stocks: list[USStockData] = []


# ── 내부 헬퍼 ──


def _format_market_cap(value: float) -> str:
    """시가총액을 읽기 쉬운 형식으로 변환한다. Finnhub은 백만 달러 단위."""
    value_dollars = value * 1_000_000  # Finnhub marketCapitalization은 백만 달러 단위
    if value_dollars >= 1_000_000_000_000:
        return f"${value_dollars / 1_000_000_000_000:.2f}T"
    if value_dollars >= 1_000_000_000:
        return f"${value_dollars / 1_000_000_000:.1f}B"
    return f"${value:,.0f}M"


def _direction(change: float) -> str:
    if change > 0:
        return "상승"
    if change < 0:
        return "하락"
    return "보합"


# ── 수집 함수 ──


async def _fetch_quote(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """Finnhub quote API 호출."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": symbol, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("c", 0) == 0 and data.get("pc", 0) == 0:
            logger.warning("빈 quote 데이터 (%s)", symbol)
            return None
        return data
    except httpx.HTTPStatusError as e:
        logger.warning("Quote API HTTP 에러 (%s): %d", symbol, e.response.status_code)
        return None
    except httpx.RequestError as e:
        logger.warning("Quote API 네트워크 에러 (%s): %s", symbol, e)
        return None


async def _fetch_profile(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """Finnhub company profile API 호출."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": symbol, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if data.get("name") else None
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("Profile API 에러 (%s): %s", symbol, e)
        return None


async def _fetch_company_news(client: httpx.AsyncClient, symbol: str) -> list[str]:
    """Finnhub company news API — 최근 1일 뉴스 헤드라인 (최대 3개)."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": symbol,
                "from": yesterday,
                "to": today,
                "token": settings.finnhub_api_key,
            },
        )
        resp.raise_for_status()
        articles = resp.json()
        return [a["headline"] for a in (articles or [])[:3] if a.get("headline")]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("News API 에러 (%s): %s", symbol, e)
        return []


async def _fetch_indices(client: httpx.AsyncClient) -> list[USIndexData]:
    """3대 지수를 ETF 프록시로 조회한다."""
    etf_map = {
        "QQQ": "나스닥 100",
        "SPY": "S&P 500",
        "DIA": "다우존스",
    }
    results = []
    for symbol, name in etf_map.items():
        quote = await _fetch_quote(client, symbol)
        if not quote:
            continue
        close = quote["c"]
        change = quote["d"] or 0
        change_pct = quote["dp"] or 0

        results.append(USIndexData(
            name=name,
            close=f"{close:,.2f}",
            change=f"{change:+,.2f}",
            change_pct=f"{change_pct:+.2f}",
            direction=_direction(change),
        ))
    return results


async def _fetch_stock(client: httpx.AsyncClient, symbol: str) -> USStockData | None:
    """개별 종목 quote + profile + news를 수집한다. profile과 news는 병렬 호출."""
    quote = await _fetch_quote(client, symbol)
    if not quote:
        return None

    close = quote["c"]
    prev_close = quote["pc"]
    change_pct = quote["dp"] or 0

    # profile + news 병렬 수집
    profile, news = await asyncio.gather(
        _fetch_profile(client, symbol),
        _fetch_company_news(client, symbol),
    )
    name = profile.get("name", symbol) if profile else symbol
    market_cap = profile.get("marketCapitalization", 0) if profile else 0

    return USStockData(
        ticker=symbol,
        name=name,
        close=f"{close:,.2f}",
        change_pct=f"{change_pct:+.2f}",
        direction=_direction(close - prev_close),
        market_cap=_format_market_cap(market_cap) if market_cap else "",
        news=news,
    )


async def _fetch_watchlist(client: httpx.AsyncClient) -> list[USStockData]:
    """워치리스트 종목들을 병렬 수집한다."""
    symbols = [s.strip() for s in settings.nasdaq_watchlist.split(",") if s.strip()]
    results = await asyncio.gather(*[_fetch_stock(client, symbol) for symbol in symbols])
    return [s for s in results if s is not None]


async def fetch_nasdaq_summary() -> NasdaqSummary:
    """나스닥 데이터를 수집한다."""
    summary = NasdaqSummary(date=datetime.now().strftime("%Y-%m-%d"))

    async with httpx.AsyncClient(timeout=settings.api_timeout) as client:
        summary.indices = await _fetch_indices(client)
        summary.stocks = await _fetch_watchlist(client)

    logger.info("나스닥 수집 완료: 지수 %d개, 종목 %d개", len(summary.indices), len(summary.stocks))
    return summary
