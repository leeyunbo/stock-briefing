"""마켓 스캔 + 매크로 지표 수집.

나스닥 100 시세, 시장 뉴스, 실적 캘린더, 매크로 지표를 수집한다.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from app.collector.research_models import (
    EarningsCalendarItem,
    MacroIndicators,
    MarketNewsItem,
    MarketScanData,
    MarketScanStock,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

# 나스닥 100 주요 종목 (스캔 유니버스)
NASDAQ_100 = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "COST", "NFLX",
    "AMD", "ADBE", "PEP", "CSCO", "TMUS", "INTC", "INTU", "CMCSA", "TXN", "AMGN",
    "QCOM", "HON", "ISRG", "AMAT", "BKNG", "LRCX", "MU", "ADI", "ADP", "MDLZ",
    "REGN", "SNPS", "KLAC", "CDNS", "PANW", "MRVL", "ABNB", "CRWD", "PYPL", "MAR",
    "CTAS", "MELI", "ORLY", "MNST", "NXPI", "FTNT", "WDAY", "PCAR", "CEG", "DASH",
    "KDP", "PAYX", "ROST", "AEP", "GEHC", "CHTR", "ODFL", "KHC", "VRSK", "FAST",
    "DXCM", "EXC", "CTSH", "BKR", "XEL", "EA", "CCEP", "IDXX", "MCHP", "TTD",
    "FANG", "ON", "ANSS", "CSGP", "CDW", "DDOG", "GFS", "TEAM", "ZS", "BIIB",
    "ILMN", "WBD", "MDB", "MRNA", "LCID", "SIRI", "ARM", "SMCI", "PLTR", "CRM",
    "SNOW", "NOW", "COIN", "MSTR", "SOFI", "RKLB", "APP", "HOOD", "IONQ", "RGTI",
]


async def scan_market() -> MarketScanData:
    """나스닥 100 + 시장 뉴스 + 실적 캘린더를 스캔한다."""
    scan = MarketScanData(scan_date=datetime.now().strftime("%Y-%m-%d"))

    from app.core.http import get_http_client
    client = get_http_client()

    news, naver_news, earnings, stocks = await asyncio.gather(
        _scan_market_news(client),
        _scan_naver_global_news(),
        _scan_earnings_calendar(client),
        _scan_stock_quotes(client),
        return_exceptions=True,
    )

    combined_news: list[MarketNewsItem] = []
    if not isinstance(news, BaseException):
        combined_news.extend(news)
    else:
        logger.error("마켓 뉴스 스캔 실패: %s", news)
    if not isinstance(naver_news, BaseException):
        combined_news.extend(naver_news)
    else:
        logger.warning("네이버 글로벌 뉴스 수집 실패: %s", naver_news)
    scan.market_news = combined_news

    if not isinstance(earnings, BaseException):
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        scan.earnings_today = [e for e in earnings if e.date == today]
        scan.earnings_tomorrow = [e for e in earnings if e.date == tomorrow]
    else:
        logger.error("실적 캘린더 스캔 실패: %s", earnings)

    if not isinstance(stocks, BaseException):
        valid = [s for s in stocks if s.close > 0]
        sorted_by_change = sorted(valid, key=lambda s: s.change_pct, reverse=True)
        scan.top_gainers = sorted_by_change[:10]
        scan.top_losers = sorted_by_change[-10:][::-1]
        volume_surge = sorted(
            [s for s in valid if s.avg_volume > 0],
            key=lambda s: s.volume / s.avg_volume if s.avg_volume > 0 else 0,
            reverse=True,
        )
        scan.top_volume = volume_surge[:10]
    else:
        logger.error("종목 시세 스캔 실패: %s", stocks)

    logger.info(
        "마켓 스캔 완료: 상승 %d, 하락 %d, 거래량 %d, 뉴스 %d, 실적 %d건",
        len(scan.top_gainers), len(scan.top_losers), len(scan.top_volume),
        len(scan.market_news), len(scan.earnings_today) + len(scan.earnings_tomorrow),
    )
    return scan


_GLOBAL_NEWS_KEYWORDS = [
    "세계경제",
    "국제정세",
    "미국 증시",
    "글로벌 시장",
]


async def _scan_naver_global_news() -> list[MarketNewsItem]:
    """네이버 뉴스에서 글로벌/지정학 뉴스를 수집한다."""
    from app.collector.news import fetch_news

    tasks = [fetch_news(query=kw, count=5) for kw in _GLOBAL_NEWS_KEYWORDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_links: set[str] = set()
    items: list[MarketNewsItem] = []

    for result in results:
        if isinstance(result, Exception):
            logger.warning("네이버 글로벌 뉴스 에러: %s", result)
            continue
        for article in result:
            if article.link not in seen_links:
                seen_links.add(article.link)
                items.append(MarketNewsItem(
                    headline=article.title,
                    summary=article.description[:300],
                    source="naver",
                    url=article.link,
                ))

    logger.info("네이버 글로벌 뉴스 %d건 수집", len(items))
    return items[:15]


async def _scan_market_news(client: httpx.AsyncClient) -> list[MarketNewsItem]:
    """Finnhub 시장 뉴스 수집."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": get_settings().finnhub_api_key},
        )
        resp.raise_for_status()
        articles = resp.json() or []
        return [
            MarketNewsItem(
                headline=a.get("headline", ""),
                summary=a.get("summary", "")[:300],
                source=a.get("source", ""),
                url=a.get("url", ""),
                related=a.get("related", ""),
                datetime_ts=a.get("datetime", 0),
            )
            for a in articles[:20]
        ]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("마켓 뉴스 에러: %s", e)
        return []


async def _scan_earnings_calendar(client: httpx.AsyncClient) -> list[EarningsCalendarItem]:
    """Finnhub 실적 발표 캘린더."""
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={"from": today, "to": tomorrow, "token": get_settings().finnhub_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("earningsCalendar", [])
        return [
            EarningsCalendarItem(
                ticker=item.get("symbol", ""),
                date=item.get("date", ""),
                eps_estimate=item.get("epsEstimate"),
                revenue_estimate=item.get("revenueEstimate"),
            )
            for item in items
            if item.get("symbol") in NASDAQ_100
        ]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("실적 캘린더 에러: %s", e)
        return []


async def _scan_stock_quotes(client: httpx.AsyncClient) -> list[MarketScanStock]:
    """나스닥 100 종목의 시세를 yfinance로 일괄 수집한다."""
    return await asyncio.to_thread(_yf_bulk_quotes)


def _yf_bulk_quotes() -> list[MarketScanStock]:
    """yfinance로 나스닥 100 종목 일괄 시세 조회 (동기)."""
    import yfinance as yf

    tickers = yf.Tickers(" ".join(NASDAQ_100))
    results = []
    for symbol in NASDAQ_100:
        try:
            t = tickers.tickers.get(symbol)
            if not t:
                continue
            info = t.fast_info
            hist = t.history(period="5d")
            if hist.empty:
                continue
            close = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            change_pct = ((close - prev) / prev * 100) if prev != 0 else 0
            volume = int(hist["Volume"].iloc[-1])

            results.append(MarketScanStock(
                ticker=symbol,
                close=round(close, 2),
                change_pct=round(change_pct, 2),
                volume=volume,
                avg_volume=int(getattr(info, "three_month_average_volume", 0) or 0),
                market_cap=float(getattr(info, "market_cap", 0) or 0),
            ))
        except Exception as e:
            logger.warning("yfinance 시세 에러 (%s): %s", symbol, e)
    return results


# ── 매크로 지표 수집 ──


async def fetch_macro_indicators() -> MacroIndicators:
    """VIX, 금리, 달러, 주요 지수, 원자재, Fear & Greed를 수집한다."""
    yf_task = asyncio.to_thread(_yf_macro_quotes)
    fg_task = _fetch_fear_greed()

    yf_result, fg_result = await asyncio.gather(yf_task, fg_task, return_exceptions=True)

    macro = MacroIndicators()

    if not isinstance(yf_result, BaseException) and yf_result:
        for field, value in yf_result.items():
            setattr(macro, field, value)
    else:
        logger.error("매크로 yfinance 수집 실패: %s", yf_result)

    if not isinstance(fg_result, BaseException) and fg_result:
        macro.fear_greed_value = fg_result.get("value")
        macro.fear_greed_label = fg_result.get("label", "")
    else:
        logger.warning("Fear & Greed 수집 실패: %s", fg_result)

    logger.info("매크로 지표 수집 완료: VIX=%s, 10Y=%s, F&G=%s",
                macro.vix, macro.treasury_10y, macro.fear_greed_value)
    return macro


def _yf_macro_quotes() -> dict:
    """yfinance로 매크로 지표를 일괄 조회한다 (동기)."""
    import yfinance as yf

    symbols = {
        "^VIX": ("vix", "vix_change"),
        "^TNX": ("treasury_10y", "treasury_10y_change"),
        "DX-Y.NYB": ("dxy", "dxy_change"),
        "^GSPC": ("sp500_close", "sp500_change_pct"),
        "^IXIC": ("nasdaq_close", "nasdaq_change_pct"),
        "^DJI": ("dow_close", "dow_change_pct"),
        "GC=F": ("gold_close", "gold_change_pct"),
        "CL=F": ("wti_close", "wti_change_pct"),
    }

    result = {}
    tickers = yf.Tickers(" ".join(symbols.keys()))

    for symbol, (close_field, change_field) in symbols.items():
        try:
            t = tickers.tickers.get(symbol)
            if not t:
                continue
            hist = t.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            close = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            if "change_pct" in change_field:
                change = ((close - prev) / prev * 100) if prev != 0 else 0
                result[close_field] = round(close, 2)
                result[change_field] = round(change, 2)
            else:
                # VIX, 10Y, DXY: 절대 변화량
                result[close_field] = round(close, 2)
                result[change_field] = round(close - prev, 2)
        except Exception as e:
            logger.warning("매크로 yfinance 에러 (%s): %s", symbol, e)

    return result


async def _fetch_fear_greed() -> dict | None:
    """CNN Fear & Greed Index를 조회한다."""
    from app.core.http import get_http_client

    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        client = get_http_client()
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        rating = fg.get("rating", "")
        if score is not None:
            return {"value": int(round(score)), "label": rating}
    except Exception as e:
        logger.warning("Fear & Greed 에러: %s", e)
    return None
