"""한국 종목 딥 리서치 — 네이버 금융 API로 수집.

엔드포인트:
- 기업정보: m.stock.naver.com/api/stock/{code}/basic
- 재무제표: m.stock.naver.com/api/stock/{code}/finance
- 실시간시세: polling.finance.naver.com/api/realtime/domestic/stock/{code}
- 1년주가:  api.stock.naver.com/chart/domestic/item/{code}/day
- 종목검색: ac.stock.naver.com/ac?q=삼성전자&target=stock
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

import httpx

from app.collector.kr_research_models import (
    KRCompanyProfile,
    KRFinancialRow,
    KRQuoteData,
    KRStockResearchData,
)
from app.collector.research_models import PriceHistoryPoint
from app.core.http import get_http_client

logger = logging.getLogger(__name__)

NAVER_STOCK_API = "https://m.stock.naver.com/api"
NAVER_POLLING_API = "https://polling.finance.naver.com/api/realtime/domestic/stock"
NAVER_CHART_API = "https://api.stock.naver.com/chart/domestic/item"
NAVER_AC_API = "https://ac.stock.naver.com/ac"
HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── 마켓 판별 ──


def detect_market(ticker: str) -> str:
    """티커를 보고 KR / US 시장을 판별한다.

    - 6자리 숫자 → KR
    - 한글 포함 → KR
    - 나머지 → US
    """
    ticker = ticker.strip()
    if re.fullmatch(r"\d{6}", ticker):
        return "KR"
    if re.search(r"[가-힣]", ticker):
        return "KR"
    return "US"


# ── 종목 검색 (이름 → 코드) ──


async def resolve_kr_ticker(name_or_code: str) -> str:
    """한글 종목명 또는 코드를 6자리 item code로 변환한다.

    이미 6자리 숫자면 그대로 반환. 한글이면 네이버 자동완성 API로 검색.
    """
    name_or_code = name_or_code.strip()
    if re.fullmatch(r"\d{6}", name_or_code):
        return name_or_code

    client = get_http_client()
    try:
        resp = await client.get(
            NAVER_AC_API,
            params={"q": name_or_code, "target": "stock"},
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            logger.warning("종목 검색 결과 없음: %s", name_or_code)
            return name_or_code
        # items[0] = [코드, 종목명, 시장, ...]
        first = items[0]
        if isinstance(first, list) and len(first) >= 1:
            return first[0]
        return name_or_code
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("종목 검색 에러 (%s): %s", name_or_code, e)
        return name_or_code


# ── 메인 수집 함수 ──


async def fetch_kr_stock_research(ticker: str) -> KRStockResearchData:
    """한국 종목의 심화 리서치 데이터를 수집한다."""
    code = await resolve_kr_ticker(ticker)
    data = KRStockResearchData(ticker=ticker, code=code)

    results = dict(zip(
        ["basic", "quote", "finance", "chart", "news"],
        await asyncio.gather(
            _fetch_basic(code),
            _fetch_quote(code),
            _fetch_finance(code),
            _fetch_price_history(code),
            _fetch_kr_news(ticker, code),
            return_exceptions=True,
        ),
    ))

    def _ok(key: str):
        v = results[key]
        return v if not isinstance(v, BaseException) and v else None

    if _ok("basic"):
        data.profile = results["basic"]
    if _ok("quote"):
        data.quote = results["quote"]
    if _ok("finance"):
        data.financials = results["finance"]
    if _ok("chart"):
        data.price_history = results["chart"]
    if _ok("news"):
        data.news_headlines = results["news"]

    for name, r in results.items():
        if isinstance(r, BaseException):
            logger.warning("KR 리서치 수집 [%s] 실패: %s", name, r)

    logger.info(
        "KR 리서치 수집 완료 [%s/%s]: profile=%s, financials=%d, prices=%d, news=%d",
        ticker, code, bool(data.profile.name), len(data.financials),
        len(data.price_history), len(data.news_headlines),
    )
    return data


# ── 개별 수집 헬퍼 ──


async def _fetch_basic(code: str) -> KRCompanyProfile | None:
    """기업 기본 정보를 조회한다."""
    client = get_http_client()
    try:
        resp = await client.get(
            f"{NAVER_STOCK_API}/stock/{code}/basic",
            headers=HEADERS,
        )
        resp.raise_for_status()
        d = resp.json()

        # 시가총액: "1,234,567억 원" 형태 → 정수 변환
        market_cap_raw = d.get("marketCap", "0")
        market_cap = _parse_int(market_cap_raw)

        return KRCompanyProfile(
            name=d.get("stockName", ""),
            code=code,
            market=d.get("stockExchangeType", {}).get("name", ""),
            industry=d.get("industryCodeType", {}).get("name", ""),
            market_cap=market_cap,
            per=_safe_float(d.get("per")),
            pbr=_safe_float(d.get("pbr")),
            dividend_yield=_safe_float(d.get("dividendYield")),
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("KR 기본정보 에러 (%s): %s", code, e)
        return None


async def _fetch_quote(code: str) -> KRQuoteData | None:
    """실시간 시세를 조회한다."""
    try:
        async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
            resp = await client.get(f"{NAVER_POLLING_API}/{code}")
            resp.raise_for_status()
            d = resp.json()["datas"][0]

            return KRQuoteData(
                current=_parse_int(d.get("closePrice", "0")),
                change=_parse_int(d.get("compareToPreviousClosePrice", "0")),
                change_pct=_safe_float(d.get("fluctuationsRatio")) or 0,
                high=_parse_int(d.get("highPrice", "0")),
                low=_parse_int(d.get("lowPrice", "0")),
                open=_parse_int(d.get("openPrice", "0")),
                prev_close=_parse_int(d.get("previousClosePrice", "0")),
                volume=_parse_int(d.get("accumulatedTradingVolume", "0")),
            )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("KR 시세 에러 (%s): %s", code, e)
        return None
    except (KeyError, IndexError) as e:
        logger.warning("KR 시세 파싱 에러 (%s): %s", code, e)
        return None


async def _fetch_finance(code: str) -> list[KRFinancialRow]:
    """재무제표를 조회한다 (연간 + 분기)."""
    rows: list[KRFinancialRow] = []
    client = get_http_client()

    for period_type, freq in [("annual", "annual"), ("quarterly", "quarter")]:
        try:
            resp = await client.get(
                f"{NAVER_STOCK_API}/stock/{code}/finance/{freq}",
                headers=HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

            # 네이버 재무제표 응답 구조: { "financeInfo": [...] } 또는 직접 리스트
            finance_items = data if isinstance(data, list) else data.get("financeInfo", [])

            for item in finance_items:
                rows.append(KRFinancialRow(
                    period=item.get("date", item.get("period", "")),
                    period_type=period_type,
                    revenue=_safe_float(item.get("revenue", item.get("salesAmount"))),
                    operating_income=_safe_float(item.get("operatingProfit", item.get("operatingIncome"))),
                    net_income=_safe_float(item.get("netIncome")),
                    eps=_safe_float(item.get("eps")),
                    roe=_safe_float(item.get("roe")),
                    debt_ratio=_safe_float(item.get("debtRatio")),
                ))
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning("KR 재무제표 에러 (%s, %s): %s", code, freq, e)

    return rows


async def _fetch_price_history(code: str) -> list[PriceHistoryPoint]:
    """1년 일봉 주가를 조회한다."""
    today = datetime.now()
    start = (today - timedelta(days=365)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            resp = await client.get(
                f"{NAVER_CHART_API}/{code}/day",
                params={"startDateTime": start, "endDateTime": end},
            )
            resp.raise_for_status()
            data = resp.json()
            prices = data if isinstance(data, list) else data.get("priceInfos", [])

            result = []
            for p in prices:
                try:
                    result.append(PriceHistoryPoint(
                        date=p.get("localDate", p.get("date", "")),
                        close=float(p.get("closePrice", 0)),
                        volume=int(p.get("accumulatedTradingVolume", 0)),
                    ))
                except (ValueError, TypeError):
                    continue
            return result
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("KR 주가 히스토리 에러 (%s): %s", code, e)
        return []


async def _fetch_kr_news(ticker: str, code: str) -> list[str]:
    """종목 관련 뉴스 헤드라인을 수집한다 (기존 fetch_news 재사용)."""
    from app.collector.news import fetch_news

    # 종목명으로 검색 (코드보다 종목명이 뉴스 검색에 적합)
    name = ticker if re.search(r"[가-힣]", ticker) else code
    articles = await fetch_news(query=f"{name} 주가", count=10)
    return [a.title for a in articles]


# ── 유틸 ──


def _parse_int(value) -> int:
    """문자열에서 정수를 추출한다 (콤마, 공백 제거)."""
    if value is None:
        return 0
    s = str(value).replace(",", "").replace(" ", "").replace("억", "").replace("원", "")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _safe_float(value) -> float | None:
    """안전하게 float 변환."""
    if value is None:
        return None
    try:
        s = str(value).replace(",", "").replace("%", "")
        f = float(s)
        import math
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None
