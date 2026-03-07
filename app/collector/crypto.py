"""코인 데이터 수집 모듈.

yfinance로 가격/거래량, CoinGecko 무료 API로 시총/순위/유통량 등 메타데이터를 수집한다.
"""

import asyncio
import logging

import httpx

from app.collector.research_models import CandidateScreenData

logger = logging.getLogger(__name__)

# 코인 상위 10종목 (yfinance 티커)
CRYPTO_TOP10 = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "LINK-USD", "DOT-USD",
]

# CoinGecko API용 ID 매핑
CRYPTO_COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "DOT-USD": "polkadot",
}

# CoinGecko → 사람이 읽을 수 있는 이름
_CRYPTO_NAMES = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "BNB",
    "XRP-USD": "XRP",
    "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin",
    "AVAX-USD": "Avalanche",
    "LINK-USD": "Chainlink",
    "DOT-USD": "Polkadot",
}

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


async def screen_crypto() -> list[CandidateScreenData]:
    """코인 상위 10종목 스크리닝. yfinance 가격 + CoinGecko 메타데이터."""
    yf_task = asyncio.to_thread(_yf_crypto_quotes)
    cg_task = _fetch_coingecko_data()

    yf_data, cg_data = await asyncio.gather(yf_task, cg_task, return_exceptions=True)

    if isinstance(yf_data, BaseException):
        logger.error("코인 yfinance 수집 실패: %s", yf_data)
        yf_data = {}
    if isinstance(cg_data, BaseException):
        logger.error("코인 CoinGecko 수집 실패: %s", cg_data)
        cg_data = {}

    results: list[CandidateScreenData] = []
    for ticker in CRYPTO_TOP10:
        yf = yf_data.get(ticker, {})
        cg = cg_data.get(ticker, {})

        close = yf.get("close") or cg.get("current_price") or 0
        if close <= 0:
            continue

        change_pct_1d = yf.get("change_pct") or cg.get("price_change_percentage_24h") or 0
        market_cap = yf.get("market_cap") or cg.get("market_cap") or 0
        # market_cap을 백만 달러 단위로 변환 (CoinGecko는 절대값)
        if market_cap > 1_000_000_000:  # 10억 이상이면 절대값으로 간주
            market_cap = market_cap / 1_000_000

        week52_high = yf.get("week52_high")
        week52_low = yf.get("week52_low")

        results.append(CandidateScreenData(
            ticker=ticker,
            name=cg.get("name") or _CRYPTO_NAMES.get(ticker, ticker),
            industry="Cryptocurrency",
            close=round(close, 2),
            change_pct_1d=round(change_pct_1d, 2),
            market_cap=round(market_cap, 0),
            week52_high=week52_high,
            week52_low=week52_low,
            # 코인에 해당 없는 재무지표
            pe_ttm=None,
            ps_ttm=None,
            pb_annual=None,
            roe_ttm=None,
            gross_margin_ttm=None,
            operating_margin_ttm=None,
            revenue_growth_3y=None,
            eps_growth_3y=None,
            beta=None,
            analyst_buy_pct=None,
        ))

    logger.info("코인 스크리닝 완료: %d종목", len(results))
    return results


def _yf_crypto_quotes() -> dict[str, dict]:
    """yfinance로 코인 10종목 가격/거래량을 일괄 조회한다 (동기)."""
    import yfinance as yf

    tickers = yf.Tickers(" ".join(CRYPTO_TOP10))
    results: dict[str, dict] = {}

    for symbol in CRYPTO_TOP10:
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

            # 52주 고저 (1년 히스토리)
            hist_1y = t.history(period="1y")
            week52_high = float(hist_1y["Close"].max()) if not hist_1y.empty else None
            week52_low = float(hist_1y["Close"].min()) if not hist_1y.empty else None

            results[symbol] = {
                "close": round(close, 2),
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "market_cap": float(getattr(info, "market_cap", 0) or 0),
                "week52_high": round(week52_high, 2) if week52_high else None,
                "week52_low": round(week52_low, 2) if week52_low else None,
            }
        except Exception as e:
            logger.warning("코인 yfinance 에러 (%s): %s", symbol, e)

    return results


async def _fetch_coingecko_data() -> dict[str, dict]:
    """CoinGecko /coins/markets에서 코인 메타데이터를 일괄 조회한다."""
    ids = ",".join(CRYPTO_COINGECKO_IDS.values())

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "ids": ids,
                    "order": "market_cap_desc",
                    "sparkline": "false",
                },
            )
            resp.raise_for_status()
            coins = resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("CoinGecko API 에러: %s", e)
        return {}

    # CoinGecko ID → yfinance 티커 역매핑
    id_to_ticker = {v: k for k, v in CRYPTO_COINGECKO_IDS.items()}

    results: dict[str, dict] = {}
    for coin in coins:
        cg_id = coin.get("id", "")
        ticker = id_to_ticker.get(cg_id)
        if not ticker:
            continue

        results[ticker] = {
            "name": coin.get("name", ""),
            "current_price": coin.get("current_price", 0),
            "market_cap": coin.get("market_cap", 0),
            "market_cap_rank": coin.get("market_cap_rank"),
            "total_volume": coin.get("total_volume", 0),
            "circulating_supply": coin.get("circulating_supply", 0),
            "ath_change_percentage": coin.get("ath_change_percentage", 0),
            "price_change_percentage_24h": coin.get("price_change_percentage_24h", 0),
        }

    logger.info("CoinGecko 데이터 수집: %d종목", len(results))
    return results
