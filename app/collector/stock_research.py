"""종목 딥 리서치 + 후보 스크리닝.

Finnhub + yfinance + SEC EDGAR로 종목별 심화 데이터를 수집한다.
모델은 research_models, 마켓 스캔은 market_scan 모듈에 분리.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from app.collector.research_models import (
    AnalystRecommendation,
    BalanceSheetRow,
    BasicFinancials,
    CandidateScreenData,
    CashFlowRow,
    CompanyNews,
    CompanyProfile,
    EarningsData,
    IncomeStatementRow,
    PeerFinancials,
    PriceHistoryPoint,
    QuoteData,
    RecentFiling,
    StockResearchData,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
SEC_BASE = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


# ── 딥 리서치 ──


async def fetch_stock_research(ticker: str) -> StockResearchData:
    """특정 종목의 심화 리서치 데이터를 수집한다."""
    data = StockResearchData(ticker=ticker)

    from app.core.http import get_http_client
    client = get_http_client()

    tasks = {
        "quote": _research_quote(client, ticker),
        "profile": _research_profile(client, ticker),
        "peers": _research_peers(client, ticker),
        "recommendations": _research_recommendations(client, ticker),
        "earnings": _research_earnings(client, ticker),
        "metrics": _research_metrics(client, ticker),
        "news": _research_news(client, ticker),
        "yfinance": asyncio.to_thread(_fetch_yfinance_data, ticker),
        "sec": _research_sec_filings(ticker),
    }
    results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values(), return_exceptions=True)))

    def _ok(key: str):
        v = results[key]
        return v if not isinstance(v, BaseException) and v else None

    if _ok("quote"):
        data.quote = results["quote"]
    if _ok("profile"):
        data.profile = results["profile"]
    if _ok("peers"):
        data.peers = results["peers"]
    if _ok("recommendations"):
        data.recommendations = results["recommendations"]
    if _ok("earnings"):
        data.earnings = results["earnings"]
    if _ok("metrics"):
        data.financials = results["metrics"]
    if _ok("news"):
        data.news = results["news"]
    if _ok("yfinance"):
        yf_data = results["yfinance"]
        data.income_statements = yf_data.get("income", [])
        data.balance_sheets = yf_data.get("balance", [])
        data.cash_flows = yf_data.get("cashflow", [])
        data.price_history = yf_data.get("price_history", [])
    if _ok("sec"):
        data.sec_filings = results["sec"]

    for name, r in results.items():
        if isinstance(r, BaseException):
            logger.warning("리서치 수집 [%s] 실패: %s", name, r)

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
            params={"symbol": ticker, "token": get_settings().finnhub_api_key},
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
            params={"symbol": ticker, "token": get_settings().finnhub_api_key},
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
            params={"symbol": ticker, "token": get_settings().finnhub_api_key},
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
            params={"symbol": ticker, "token": get_settings().finnhub_api_key},
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
            params={"symbol": ticker, "token": get_settings().finnhub_api_key},
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
            params={"symbol": ticker, "metric": "all", "token": get_settings().finnhub_api_key},
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
                "token": get_settings().finnhub_api_key,
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
    try:
        profile_resp, metric_resp = await asyncio.gather(
            client.get(f"{FINNHUB_BASE}/stock/profile2",
                       params={"symbol": ticker, "token": get_settings().finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/metric",
                       params={"symbol": ticker, "metric": "all", "token": get_settings().finnhub_api_key}),
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

            padded_cik = cik.zfill(10)
            resp = await client.get(f"{SEC_BASE}/submissions/CIK{padded_cik}.json")
            resp.raise_for_status()
            submissions = resp.json()

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


# ── 후보 종목 경량 스크리닝 ──


async def screen_candidates(tickers: list[str]) -> list[CandidateScreenData]:
    """Claude가 추천한 후보 종목들의 재무지표를 병렬 수집한다."""
    from app.core.http import get_http_client
    client = get_http_client()
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
    try:
        profile_resp, metric_resp, rec_resp, quote_resp = await asyncio.gather(
            client.get(f"{FINNHUB_BASE}/stock/profile2",
                       params={"symbol": ticker, "token": get_settings().finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/metric",
                       params={"symbol": ticker, "metric": "all", "token": get_settings().finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/stock/recommendation",
                       params={"symbol": ticker, "token": get_settings().finnhub_api_key}),
            client.get(f"{FINNHUB_BASE}/quote",
                       params={"symbol": ticker, "token": get_settings().finnhub_api_key}),
        )

        profile = profile_resp.json() if profile_resp.status_code == 200 else {}
        metric_data = metric_resp.json() if metric_resp.status_code == 200 else {}
        recs = rec_resp.json() if rec_resp.status_code == 200 else []
        quote = quote_resp.json() if quote_resp.status_code == 200 else {}

        m = metric_data.get("metric", {})
        if not profile.get("name") and not m:
            return None

        analyst_buy_pct = None
        if recs and isinstance(recs, list) and len(recs) > 0:
            latest = recs[0]
            total = (latest.get("strongBuy", 0) + latest.get("buy", 0) +
                     latest.get("hold", 0) + latest.get("sell", 0) + latest.get("strongSell", 0))
            if total > 0:
                buy_count = latest.get("strongBuy", 0) + latest.get("buy", 0)
                analyst_buy_pct = round(buy_count / total * 100, 1)

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
