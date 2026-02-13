"""시장 데이터 수집기 - 네이버 금융 API로 코스피/코스닥 지수 및 주요 종목 데이터를 수집한다."""

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

NAVER_STOCK_API = "https://m.stock.naver.com/api"
NAVER_POLLING_API = "https://polling.finance.naver.com/api/realtime/domestic/stock"
HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── Pydantic 모델 계층 (스프링의 Jackson DTO 중첩과 동일) ──


class IndexData(BaseModel):
    """지수 데이터 (코스피/코스닥)."""

    name: str
    close: str
    change: str
    change_pct: str
    direction: str


class StockData(BaseModel):
    """개별 종목 데이터."""

    name: str
    close: str
    change_pct: str
    direction: str
    volume: str = ""


class InvestorData(BaseModel):
    """투자자별 매매동향."""

    personal: str
    foreign: str
    institutional: str


class MarketSummary(BaseModel):
    """시장 요약 — 모든 수집 데이터를 담는 최상위 모델."""

    date: str = ""
    kospi: IndexData | None = None
    kosdaq: IndexData | None = None
    kospi_top10: list[StockData] = []
    kospi_investor: InvestorData | None = None
    kosdaq_investor: InvestorData | None = None


# ── 수집 함수 ──


async def fetch_market_summary() -> MarketSummary:
    """시장 요약 데이터를 가져온다."""
    market = MarketSummary()

    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        # 코스피/코스닥 지수
        for code, field in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
            index_data = await _fetch_index(client, code)
            if index_data:
                setattr(market, field, index_data.index)
                if index_data.date:
                    market.date = index_data.date

        # 코스피 시총 TOP10
        market.kospi_top10 = await _fetch_top10(client)

        # 투자자별 매매동향
        for code, field in [("KOSPI", "kospi_investor"), ("KOSDAQ", "kosdaq_investor")]:
            investor = await _fetch_investor(client, code)
            if investor:
                setattr(market, field, investor)

    return market


class _IndexResult(BaseModel):
    """지수 조회 내부 결과 (날짜 포함)."""

    index: IndexData
    date: str = ""


async def _fetch_index(client: httpx.AsyncClient, code: str) -> _IndexResult | None:
    """코스피/코스닥 지수 데이터를 가져온다."""
    try:
        resp = await client.get(f"{NAVER_STOCK_API}/index/{code}/basic")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("지수 API HTTP 에러 (%s): %d", code, e.response.status_code)
        return None
    except httpx.RequestError as e:
        logger.warning("지수 API 네트워크 에러 (%s): %s", code, e)
        return None

    return _IndexResult(
        index=IndexData(
            name=data.get("stockName", code),
            close=data.get("closePrice", ""),
            change=data.get("compareToPreviousClosePrice", ""),
            change_pct=data.get("fluctuationsRatio", ""),
            direction=data.get("compareToPreviousPrice", {}).get("text", ""),
        ),
        date=data.get("localTradedAt", "")[:10],
    )


async def _fetch_top10(client: httpx.AsyncClient) -> list[StockData]:
    """코스피 시총 TOP10을 가져온다. 시간외 가격 반영."""
    try:
        resp = await client.get(
            f"{NAVER_STOCK_API}/stocks/marketValue",
            params={"market": "KOSPI", "page": 1, "pageSize": 10},
        )
        resp.raise_for_status()
        stocks = resp.json().get("stocks", [])
    except httpx.HTTPStatusError as e:
        logger.warning("시총 TOP10 API HTTP 에러: %d", e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("시총 TOP10 API 네트워크 에러: %s", e)
        return []

    top10: list[StockData] = []
    for s in stocks:
        item_code = s.get("itemCode", "")
        stock = await _fetch_stock_with_afterhours(client, item_code)
        if stock:
            top10.append(stock)
        else:
            top10.append(StockData(
                name=s.get("stockName", ""),
                close=s.get("closePrice", ""),
                change_pct=s.get("fluctuationsRatio", ""),
                direction=s.get("compareToPreviousPrice", {}).get("text", ""),
                volume=s.get("accumulatedTradingVolume", ""),
            ))
    return top10


async def _fetch_stock_with_afterhours(client: httpx.AsyncClient, item_code: str) -> StockData | None:
    """polling API로 시간외 반영 가격을 가져온다."""
    try:
        resp = await client.get(f"{NAVER_POLLING_API}/{item_code}")
        resp.raise_for_status()
        d = resp.json()["datas"][0]
    except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError):
        return None

    over = d.get("overMarketPriceInfo") or {}

    if over.get("overPrice"):
        return StockData(
            name=d.get("stockName", ""),
            close=over["overPrice"],
            change_pct=over.get("fluctuationsRatio", d.get("fluctuationsRatio", "")),
            direction=over.get("compareToPreviousPrice", {}).get("text",
                      d.get("compareToPreviousPrice", {}).get("text", "")),
            volume=d.get("accumulatedTradingVolume", ""),
        )

    return StockData(
        name=d.get("stockName", ""),
        close=d.get("closePrice", ""),
        change_pct=d.get("fluctuationsRatio", ""),
        direction=d.get("compareToPreviousPrice", {}).get("text", ""),
        volume=d.get("accumulatedTradingVolume", ""),
    )


async def _fetch_investor(client: httpx.AsyncClient, code: str) -> InvestorData | None:
    """투자자별 매매동향을 가져온다."""
    try:
        resp = await client.get(f"{NAVER_STOCK_API}/index/{code}/trend")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("투자자동향 API HTTP 에러 (%s): %d", code, e.response.status_code)
        return None
    except httpx.RequestError as e:
        logger.warning("투자자동향 API 네트워크 에러 (%s): %s", code, e)
        return None

    return InvestorData(
        personal=data.get("personalValue", ""),
        foreign=data.get("foreignValue", ""),
        institutional=data.get("institutionalValue", ""),
    )
