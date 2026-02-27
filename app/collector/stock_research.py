"""종목 리서치 데이터 수집기 — Finnhub + yfinance + SEC EDGAR.

세 가지 수집 모드를 제공한다:
1. scan_market()         — 시장 뉴스 + 실적 캘린더 + 나스닥100 시세 스캔
2. screen_candidates()   — Claude가 추천한 후보 종목들의 재무지표 경량 스크리닝
3. fetch_stock_research() — 특정 종목의 심화 분석 데이터를 수집

모든 필드 optional/기본값 → 개별 API 실패해도 파이프라인 중단 없음.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
SEC_BASE = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

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


# ── Pydantic 모델: 마켓 스캔 ──


class MacroIndicators(BaseModel):
    """매크로 지표 — VIX, 금리, 달러, 지수, 원자재."""
    vix: float | None = None
    vix_change: float | None = None
    treasury_10y: float | None = None
    treasury_10y_change: float | None = None
    dxy: float | None = None
    dxy_change: float | None = None
    fear_greed_value: int | None = None
    fear_greed_label: str = ""
    sp500_close: float | None = None
    sp500_change_pct: float | None = None
    nasdaq_close: float | None = None
    nasdaq_change_pct: float | None = None
    dow_close: float | None = None
    dow_change_pct: float | None = None
    gold_close: float | None = None
    gold_change_pct: float | None = None
    wti_close: float | None = None
    wti_change_pct: float | None = None


class MarketScanStock(BaseModel):
    """스캔 시 개별 종목 데이터."""
    ticker: str
    name: str = ""
    close: float = 0
    change_pct: float = 0
    volume: int = 0
    avg_volume: float = 0
    market_cap: float = 0
    pe_ratio: float = 0
    industry: str = ""


class EarningsCalendarItem(BaseModel):
    """실적 발표 캘린더 항목."""
    ticker: str
    date: str = ""
    eps_estimate: float | None = None
    revenue_estimate: float | None = None


class MarketNewsItem(BaseModel):
    """시장 뉴스 항목."""
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""
    related: str = ""
    datetime_ts: int = 0


class MarketScanData(BaseModel):
    """마켓 스캔 결과 — Claude가 종목을 선택하기 위한 데이터."""
    scan_date: str = ""
    top_gainers: list[MarketScanStock] = []
    top_losers: list[MarketScanStock] = []
    top_volume: list[MarketScanStock] = []
    earnings_today: list[EarningsCalendarItem] = []
    earnings_tomorrow: list[EarningsCalendarItem] = []
    market_news: list[MarketNewsItem] = []


# ── Pydantic 모델: 딥 리서치 ──


class CompanyProfile(BaseModel):
    """Finnhub 기업 프로필."""
    name: str = ""
    ticker: str = ""
    exchange: str = ""
    industry: str = ""
    market_cap: float = 0
    share_outstanding: float = 0
    logo: str = ""
    weburl: str = ""
    ipo: str = ""
    country: str = ""


class QuoteData(BaseModel):
    """Finnhub 실시간 시세."""
    current: float = 0
    change: float = 0
    change_pct: float = 0
    high: float = 0
    low: float = 0
    open: float = 0
    prev_close: float = 0


class BasicFinancials(BaseModel):
    """Finnhub 핵심 재무지표."""
    pe_ttm: float | None = None
    pb_annual: float | None = None
    ps_ttm: float | None = None
    roe_ttm: float | None = None
    roi_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    net_margin_ttm: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    week52_high_date: str = ""
    week52_low_date: str = ""
    revenue_growth_3y: float | None = None
    eps_growth_3y: float | None = None


class EarningsData(BaseModel):
    """분기별 EPS 데이터."""
    period: str = ""
    actual: float | None = None
    estimate: float | None = None
    surprise_pct: float | None = None


class AnalystRecommendation(BaseModel):
    """애널리스트 추천."""
    period: str = ""
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0


class CompanyNews(BaseModel):
    """기업 뉴스."""
    headline: str = ""
    summary: str = ""
    source: str = ""
    url: str = ""
    datetime_ts: int = 0


class IncomeStatementRow(BaseModel):
    """손익계산서 행."""
    period: str = ""
    period_type: str = ""  # "annual" or "quarterly"
    total_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    ebitda: float | None = None
    research_development: float | None = None
    diluted_eps: float | None = None


class BalanceSheetRow(BaseModel):
    """대차대조표 행."""
    period: str = ""
    period_type: str = ""
    total_assets: float | None = None
    total_liabilities: float | None = None
    stockholders_equity: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    net_debt: float | None = None


class CashFlowRow(BaseModel):
    """현금흐름표 행."""
    period: str = ""
    period_type: str = ""
    operating_cf: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None
    dividends_paid: float | None = None
    share_buyback: float | None = None


class PriceHistoryPoint(BaseModel):
    """일별 주가."""
    date: str
    close: float
    volume: int = 0


class RecentFiling(BaseModel):
    """SEC 공시."""
    form_type: str = ""
    filing_date: str = ""
    description: str = ""
    url: str = ""


class PeerFinancials(BaseModel):
    """Peer 기업 비교 지표."""
    ticker: str
    name: str = ""
    market_cap: float = 0
    pe_ttm: float | None = None
    pb_annual: float | None = None
    ps_ttm: float | None = None
    roe_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    revenue_growth_3y: float | None = None


class StockResearchData(BaseModel):
    """딥 리서치 최상위 모델."""
    ticker: str
    profile: CompanyProfile = CompanyProfile()
    quote: QuoteData = QuoteData()
    financials: BasicFinancials = BasicFinancials()
    earnings: list[EarningsData] = []
    recommendations: list[AnalystRecommendation] = []
    news: list[CompanyNews] = []
    peers: list[str] = []
    income_statements: list[IncomeStatementRow] = []
    balance_sheets: list[BalanceSheetRow] = []
    cash_flows: list[CashFlowRow] = []
    price_history: list[PriceHistoryPoint] = []
    sec_filings: list[RecentFiling] = []
    peer_financials: list[PeerFinancials] = []


# ══════════════════════════════════════════════
# Part 1: 마켓 스캔 (종목 선정용)
# ══════════════════════════════════════════════


async def scan_market() -> MarketScanData:
    """나스닥 100 + 시장 뉴스 + 실적 캘린더를 스캔한다."""
    scan = MarketScanData(scan_date=datetime.now().strftime("%Y-%m-%d"))

    async with httpx.AsyncClient(timeout=settings.api_timeout) as client:
        # Phase 1: 시장 뉴스 + 실적 캘린더 + 종목 시세 병렬 수집
        news_task = _scan_market_news(client)
        earnings_task = _scan_earnings_calendar(client)
        quotes_task = _scan_stock_quotes(client)

        news, earnings, stocks = await asyncio.gather(
            news_task, earnings_task, quotes_task,
            return_exceptions=True,
        )

        if not isinstance(news, BaseException):
            scan.market_news = news
        else:
            logger.error("마켓 뉴스 스캔 실패: %s", news)

        if not isinstance(earnings, BaseException):
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            scan.earnings_today = [e for e in earnings if e.date == today]
            scan.earnings_tomorrow = [e for e in earnings if e.date == tomorrow]
        else:
            logger.error("실적 캘린더 스캔 실패: %s", earnings)

        if not isinstance(stocks, BaseException):
            # 등락률 기준 정렬
            valid = [s for s in stocks if s.close > 0]
            sorted_by_change = sorted(valid, key=lambda s: s.change_pct, reverse=True)
            scan.top_gainers = sorted_by_change[:10]
            scan.top_losers = sorted_by_change[-10:][::-1]
            # 거래량/평균거래량 비율 상위
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


async def _scan_market_news(client: httpx.AsyncClient) -> list[MarketNewsItem]:
    """Finnhub 시장 뉴스 수집."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": settings.finnhub_api_key},
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
            params={"from": today, "to": tomorrow, "token": settings.finnhub_api_key},
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


# ══════════════════════════════════════════════
# Part 1.5: 매크로 지표 수집
# ══════════════════════════════════════════════


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
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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


# ══════════════════════════════════════════════
# Part 2: 딥 리서치 데이터 수집
# ══════════════════════════════════════════════


async def fetch_stock_research(ticker: str) -> StockResearchData:
    """특정 종목의 심화 리서치 데이터를 수집한다."""
    data = StockResearchData(ticker=ticker)

    async with httpx.AsyncClient(timeout=settings.api_timeout) as client:
        # Phase 1: 타겟 종목 병렬 수집
        results = await asyncio.gather(
            _research_quote(client, ticker),
            _research_profile(client, ticker),
            _research_peers(client, ticker),
            _research_recommendations(client, ticker),
            _research_earnings(client, ticker),
            _research_metrics(client, ticker),
            _research_news(client, ticker),
            asyncio.to_thread(_fetch_yfinance_data, ticker),
            _research_sec_filings(ticker),
            return_exceptions=True,
        )

        # 결과 할당
        if not isinstance(results[0], BaseException) and results[0]:
            data.quote = results[0]
        if not isinstance(results[1], BaseException) and results[1]:
            data.profile = results[1]
        if not isinstance(results[2], BaseException) and results[2]:
            data.peers = results[2]
        if not isinstance(results[3], BaseException) and results[3]:
            data.recommendations = results[3]
        if not isinstance(results[4], BaseException) and results[4]:
            data.earnings = results[4]
        if not isinstance(results[5], BaseException) and results[5]:
            data.financials = results[5]
        if not isinstance(results[6], BaseException) and results[6]:
            data.news = results[6]
        if not isinstance(results[7], BaseException) and results[7]:
            yf_data = results[7]
            data.income_statements = yf_data.get("income", [])
            data.balance_sheets = yf_data.get("balance", [])
            data.cash_flows = yf_data.get("cashflow", [])
            data.price_history = yf_data.get("price_history", [])
        if not isinstance(results[8], BaseException) and results[8]:
            data.sec_filings = results[8]

        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.warning("리서치 수집 Phase1[%d] 실패: %s", i, r)

        # Phase 2: Peer 비교 지표 수집
        if data.peers:
            peer_results = await asyncio.gather(
                *[_research_peer_financials(client, p) for p in data.peers[:5]],
                return_exceptions=True,
            )
            for r in peer_results:
                if not isinstance(r, BaseException) and r:
                    data.peer_financials.append(r)

    logger.info(
        "리서치 수집 완료 [%s]: profile=%s, earnings=%d, peers=%d, filings=%d",
        ticker, bool(data.profile.name), len(data.earnings),
        len(data.peer_financials), len(data.sec_filings),
    )
    return data


# ── Finnhub 딥 리서치 헬퍼 ──


async def _research_quote(client: httpx.AsyncClient, ticker: str) -> QuoteData | None:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        d = resp.json()
        if d.get("c", 0) == 0:
            return None
        return QuoteData(
            current=d["c"], change=d.get("d", 0) or 0,
            change_pct=d.get("dp", 0) or 0, high=d.get("h", 0) or 0,
            low=d.get("l", 0) or 0, open=d.get("o", 0) or 0,
            prev_close=d.get("pc", 0) or 0,
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Quote 에러 (%s): %s", ticker, e)
        return None


async def _research_profile(client: httpx.AsyncClient, ticker: str) -> CompanyProfile | None:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        d = resp.json()
        if not d.get("name"):
            return None
        return CompanyProfile(
            name=d.get("name", ""), ticker=d.get("ticker", ticker),
            exchange=d.get("exchange", ""), industry=d.get("finnhubIndustry", ""),
            market_cap=d.get("marketCapitalization", 0) or 0,
            share_outstanding=d.get("shareOutstanding", 0) or 0,
            logo=d.get("logo", ""), weburl=d.get("weburl", ""),
            ipo=d.get("ipo", ""), country=d.get("country", ""),
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Profile 에러 (%s): %s", ticker, e)
        return None


async def _research_peers(client: httpx.AsyncClient, ticker: str) -> list[str]:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/peers",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        peers = resp.json() or []
        return [p for p in peers if p != ticker][:10]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Peers 에러 (%s): %s", ticker, e)
        return []


async def _research_recommendations(client: httpx.AsyncClient, ticker: str) -> list[AnalystRecommendation]:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/recommendation",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        items = resp.json() or []
        return [
            AnalystRecommendation(
                period=r.get("period", ""),
                strong_buy=r.get("strongBuy", 0),
                buy=r.get("buy", 0), hold=r.get("hold", 0),
                sell=r.get("sell", 0), strong_sell=r.get("strongSell", 0),
            )
            for r in items[:4]
        ]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Recommendation 에러 (%s): %s", ticker, e)
        return []


async def _research_earnings(client: httpx.AsyncClient, ticker: str) -> list[EarningsData]:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/earnings",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        items = resp.json() or []
        return [
            EarningsData(
                period=e.get("period", ""),
                actual=e.get("actual"),
                estimate=e.get("estimate"),
                surprise_pct=e.get("surprisePercent"),
            )
            for e in items[:4]
        ]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Earnings 에러 (%s): %s", ticker, e)
        return []


async def _research_metrics(client: httpx.AsyncClient, ticker: str) -> BasicFinancials | None:
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/metric",
            params={"symbol": ticker, "metric": "all", "token": settings.finnhub_api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        m = data.get("metric", {})
        if not m:
            return None
        return BasicFinancials(
            pe_ttm=m.get("peTTM"),
            pb_annual=m.get("pbAnnual"),
            ps_ttm=m.get("psTTM"),
            roe_ttm=m.get("roeTTM"),
            roi_ttm=m.get("roiTTM"),
            gross_margin_ttm=m.get("grossMarginTTM"),
            operating_margin_ttm=m.get("operatingMarginTTM"),
            net_margin_ttm=m.get("netProfitMarginTTM"),
            debt_equity=m.get("totalDebt/totalEquityAnnual"),
            current_ratio=m.get("currentRatioAnnual"),
            dividend_yield=m.get("dividendYieldIndicatedAnnual"),
            beta=m.get("beta"),
            week52_high=m.get("52WeekHigh"),
            week52_low=m.get("52WeekLow"),
            week52_high_date=m.get("52WeekHighDate", ""),
            week52_low_date=m.get("52WeekLowDate", ""),
            revenue_growth_3y=m.get("revenueGrowth3Y"),
            eps_growth_3y=m.get("epsGrowth3Y"),
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 Metrics 에러 (%s): %s", ticker, e)
        return None


async def _research_news(client: httpx.AsyncClient, ticker: str) -> list[CompanyNews]:
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker, "from": week_ago, "to": today,
                "token": settings.finnhub_api_key,
            },
        )
        resp.raise_for_status()
        articles = resp.json() or []
        return [
            CompanyNews(
                headline=a.get("headline", ""),
                summary=a.get("summary", "")[:400],
                source=a.get("source", ""),
                url=a.get("url", ""),
                datetime_ts=a.get("datetime", 0),
            )
            for a in articles[:10]
        ]
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("리서치 News 에러 (%s): %s", ticker, e)
        return []


async def _research_peer_financials(client: httpx.AsyncClient, ticker: str) -> PeerFinancials | None:
    """Peer 기업의 비교용 지표를 수집한다."""
    try:
        profile_resp, metric_resp = await asyncio.gather(
            client.get(f"{FINNHUB_BASE}/stock/profile2",
                       params={"symbol": ticker, "token": settings.finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/metric",
                       params={"symbol": ticker, "metric": "all", "token": settings.finnhub_api_key}),
        )
        profile = profile_resp.json() if profile_resp.status_code == 200 else {}
        metrics_data = metric_resp.json() if metric_resp.status_code == 200 else {}
        m = metrics_data.get("metric", {})

        return PeerFinancials(
            ticker=ticker,
            name=profile.get("name", ticker),
            market_cap=profile.get("marketCapitalization", 0) or 0,
            pe_ttm=m.get("peTTM"),
            pb_annual=m.get("pbAnnual"),
            ps_ttm=m.get("psTTM"),
            roe_ttm=m.get("roeTTM"),
            gross_margin_ttm=m.get("grossMarginTTM"),
            operating_margin_ttm=m.get("operatingMarginTTM"),
            revenue_growth_3y=m.get("revenueGrowth3Y"),
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("Peer 지표 에러 (%s): %s", ticker, e)
        return None


# ── yfinance 데이터 (동기, to_thread로 호출) ──


def _fetch_yfinance_data(ticker: str) -> dict:
    """yfinance로 재무제표 + 주가 히스토리를 수집한다."""
    import yfinance as yf

    stock = yf.Ticker(ticker)
    result: dict = {"income": [], "balance": [], "cashflow": [], "price_history": []}

    # 손익계산서
    try:
        for period_type, financials in [("annual", stock.financials), ("quarterly", stock.quarterly_financials)]:
            if financials is None or financials.empty:
                continue
            for col in financials.columns:
                row = financials[col]
                result["income"].append(IncomeStatementRow(
                    period=col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
                    period_type=period_type,
                    total_revenue=_safe_float(row, "Total Revenue"),
                    gross_profit=_safe_float(row, "Gross Profit"),
                    operating_income=_safe_float(row, "Operating Income"),
                    net_income=_safe_float(row, "Net Income"),
                    ebitda=_safe_float(row, "EBITDA"),
                    research_development=_safe_float(row, "Research Development"),
                    diluted_eps=_safe_float(row, "Diluted EPS"),
                ))
    except Exception as e:
        logger.warning("yfinance 손익계산서 에러 (%s): %s", ticker, e)

    # 대차대조표
    try:
        for period_type, sheet in [("annual", stock.balance_sheet), ("quarterly", stock.quarterly_balance_sheet)]:
            if sheet is None or sheet.empty:
                continue
            for col in sheet.columns:
                row = sheet[col]
                total_cash = _safe_float(row, "Cash And Cash Equivalents")
                total_debt = _safe_float(row, "Total Debt")
                result["balance"].append(BalanceSheetRow(
                    period=col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
                    period_type=period_type,
                    total_assets=_safe_float(row, "Total Assets"),
                    total_liabilities=_safe_float(row, "Total Liabilities Net Minority Interest"),
                    stockholders_equity=_safe_float(row, "Stockholders Equity"),
                    total_cash=total_cash,
                    total_debt=total_debt,
                    net_debt=(total_debt - total_cash) if total_debt is not None and total_cash is not None else None,
                ))
    except Exception as e:
        logger.warning("yfinance 대차대조표 에러 (%s): %s", ticker, e)

    # 현금흐름표
    try:
        for period_type, cf in [("annual", stock.cashflow), ("quarterly", stock.quarterly_cashflow)]:
            if cf is None or cf.empty:
                continue
            for col in cf.columns:
                row = cf[col]
                op_cf = _safe_float(row, "Operating Cash Flow")
                capex = _safe_float(row, "Capital Expenditure")
                fcf = (op_cf + capex) if op_cf is not None and capex is not None else None
                result["cashflow"].append(CashFlowRow(
                    period=col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
                    period_type=period_type,
                    operating_cf=op_cf,
                    capital_expenditure=capex,
                    free_cash_flow=fcf,
                    dividends_paid=_safe_float(row, "Common Stock Dividend Paid"),
                    share_buyback=_safe_float(row, "Repurchase Of Capital Stock"),
                ))
    except Exception as e:
        logger.warning("yfinance 현금흐름표 에러 (%s): %s", ticker, e)

    # 1년 일봉
    try:
        hist = stock.history(period="1y")
        if hist is not None and not hist.empty:
            for idx, row in hist.iterrows():
                result["price_history"].append(PriceHistoryPoint(
                    date=idx.strftime("%Y-%m-%d"),
                    close=round(float(row["Close"]), 2),
                    volume=int(row["Volume"]),
                ))
    except Exception as e:
        logger.warning("yfinance 주가 히스토리 에러 (%s): %s", ticker, e)

    return result


def _safe_float(row, key: str) -> float | None:
    """pandas Series에서 안전하게 float 추출."""
    try:
        val = row.get(key)
        if val is None:
            return None
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError, KeyError):
        return None


# ── SEC EDGAR ──


async def _research_sec_filings(ticker: str) -> list[RecentFiling]:
    """SEC EDGAR에서 최근 공시를 조회한다."""
    headers = {"User-Agent": "StockBriefing research@example.com"}

    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            # Step 1: 티커 → CIK 매핑
            resp = await client.get(SEC_TICKERS_URL)
            resp.raise_for_status()
            tickers_data = resp.json()

            cik = None
            for entry in tickers_data.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    cik = str(entry["cik_str"])
                    break
            if not cik:
                logger.warning("SEC CIK 매핑 실패 (%s)", ticker)
                return []

            # Step 2: 공시 목록 조회
            padded_cik = cik.zfill(10)
            resp = await client.get(f"{SEC_BASE}/submissions/CIK{padded_cik}.json")
            resp.raise_for_status()
            submissions = resp.json()

            # Step 3: 10-K, 10-Q, 8-K 필터링
            recent = submissions.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            descriptions = recent.get("primaryDocDescription", [])
            accessions = recent.get("accessionNumber", [])

            target_forms = {"10-K", "10-Q", "8-K"}
            filings = []
            for i, form in enumerate(forms):
                if form in target_forms and i < len(dates):
                    acc = accessions[i].replace("-", "") if i < len(accessions) else ""
                    filings.append(RecentFiling(
                        form_type=form,
                        filing_date=dates[i] if i < len(dates) else "",
                        description=descriptions[i] if i < len(descriptions) else "",
                        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5" if acc else "",
                    ))
                    if len(filings) >= 5:
                        break

            return filings
    except Exception as e:
        logger.warning("SEC EDGAR 에러 (%s): %s", ticker, e)
        return []


# ══════════════════════════════════════════════
# Part 3: 후보 종목 경량 스크리닝
# ══════════════════════════════════════════════


class CandidateScreenData(BaseModel):
    """후보 종목 스크리닝 결과 — 경량 재무지표."""
    ticker: str
    name: str = ""
    industry: str = ""
    close: float = 0
    change_pct_1d: float = 0
    change_pct_1y: float = 0
    market_cap: float = 0  # 백만 달러
    pe_ttm: float | None = None
    ps_ttm: float | None = None
    pb_annual: float | None = None
    roe_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    revenue_growth_3y: float | None = None
    eps_growth_3y: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    beta: float | None = None
    analyst_buy_pct: float | None = None  # (strongBuy+buy) / total


async def screen_candidates(tickers: list[str]) -> list[CandidateScreenData]:
    """Claude가 추천한 후보 종목들의 재무지표를 병렬 수집한다.

    Finnhub profile + metrics + recommendation을 종목당 3 API 호출.
    나스닥100 밖 종목도 처리 가능.
    """
    async with httpx.AsyncClient(timeout=settings.api_timeout) as client:
        results = await asyncio.gather(
            *[_screen_single(client, t) for t in tickers],
            return_exceptions=True,
        )

    screened = []
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("후보 스크리닝 실패: %s", r)
        elif r is not None:
            screened.append(r)

    logger.info("후보 스크리닝 완료: %d/%d 종목", len(screened), len(tickers))
    return screened


async def _screen_single(client: httpx.AsyncClient, ticker: str) -> CandidateScreenData | None:
    """단일 종목의 스크리닝 데이터를 수집한다."""
    try:
        profile_resp, metric_resp, rec_resp, quote_resp = await asyncio.gather(
            client.get(f"{FINNHUB_BASE}/stock/profile2",
                       params={"symbol": ticker, "token": settings.finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/metric",
                       params={"symbol": ticker, "metric": "all", "token": settings.finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/recommendation",
                       params={"symbol": ticker, "token": settings.finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/quote",
                       params={"symbol": ticker, "token": settings.finnhub_api_key}),
        )

        profile = profile_resp.json() if profile_resp.status_code == 200 else {}
        metric_data = metric_resp.json() if metric_resp.status_code == 200 else {}
        recs = rec_resp.json() if rec_resp.status_code == 200 else []
        quote = quote_resp.json() if quote_resp.status_code == 200 else {}

        m = metric_data.get("metric", {})
        if not profile.get("name") and not m:
            return None

        # 애널리스트 매수 비율 계산
        analyst_buy_pct = None
        if recs and isinstance(recs, list) and len(recs) > 0:
            latest = recs[0]
            total = (latest.get("strongBuy", 0) + latest.get("buy", 0) +
                     latest.get("hold", 0) + latest.get("sell", 0) + latest.get("strongSell", 0))
            if total > 0:
                buy_count = latest.get("strongBuy", 0) + latest.get("buy", 0)
                analyst_buy_pct = round(buy_count / total * 100, 1)

        # 1년 수익률 (yfinance로 빠르게)
        change_pct_1y = 0.0
        close = quote.get("c", 0) or 0
        change_pct_1d = quote.get("dp", 0) or 0

        return CandidateScreenData(
            ticker=ticker,
            name=profile.get("name", ticker),
            industry=profile.get("finnhubIndustry", ""),
            close=close,
            change_pct_1d=change_pct_1d,
            change_pct_1y=change_pct_1y,
            market_cap=profile.get("marketCapitalization", 0) or 0,
            pe_ttm=m.get("peTTM"),
            ps_ttm=m.get("psTTM"),
            pb_annual=m.get("pbAnnual"),
            roe_ttm=m.get("roeTTM"),
            gross_margin_ttm=m.get("grossMarginTTM"),
            operating_margin_ttm=m.get("operatingMarginTTM"),
            revenue_growth_3y=m.get("revenueGrowth3Y"),
            eps_growth_3y=m.get("epsGrowth3Y"),
            week52_high=m.get("52WeekHigh"),
            week52_low=m.get("52WeekLow"),
            beta=m.get("beta"),
            analyst_buy_pct=analyst_buy_pct,
        )
    except Exception as e:
        logger.warning("후보 스크리닝 에러 (%s): %s", ticker, e)
        return None
