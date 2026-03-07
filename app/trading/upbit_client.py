"""업비트 API 클라이언트 — pyupbit 래핑 (동기 → asyncio.to_thread)."""

import asyncio
import logging

import pyupbit

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class UpbitClient:
    """업비트 API 클라이언트."""

    def __init__(self, access_key: str = "", secret_key: str = ""):
        s = get_settings()
        self._access = access_key or s.upbit_access_key
        self._secret = secret_key or s.upbit_secret_key
        self._upbit = pyupbit.Upbit(self._access, self._secret) if self._access else None

    # ── 시세 ──

    async def get_candles(self, market: str, interval: str = "minute15", count: int = 200) -> list[dict]:
        """캔들 데이터 조회. interval: minute1/minute15/minute60/minute240/day/week."""
        def _fetch():
            if interval.startswith("minute"):
                unit = int(interval.replace("minute", ""))
                df = pyupbit.get_ohlcv(market, interval=f"minute{unit}", count=count)
            elif interval == "day":
                df = pyupbit.get_ohlcv(market, interval="day", count=count)
            elif interval == "week":
                df = pyupbit.get_ohlcv(market, interval="week", count=count)
            else:
                df = pyupbit.get_ohlcv(market, interval="minute15", count=count)

            if df is None or df.empty:
                return []

            df = df.reset_index()
            # pyupbit: index(datetime), open, high, low, close, volume, value
            df = df.rename(columns={"index": "datetime"})
            return df.to_dict("records")

        return await asyncio.to_thread(_fetch)

    async def get_ticker(self, markets: list[str]) -> list[dict]:
        """현재가 정보 조회."""
        def _fetch():
            return pyupbit.get_current_price(markets, verbose=True) or []

        result = await asyncio.to_thread(_fetch)
        if isinstance(result, dict):
            return [result]
        return result if result else []

    async def get_orderbook(self, markets: list[str]) -> list[dict]:
        """호가 정보 조회."""
        def _fetch():
            return pyupbit.get_orderbook(markets) or []

        return await asyncio.to_thread(_fetch)

    # ── 계좌 ──

    async def get_balances(self) -> list[dict]:
        """전체 잔고 조회."""
        if not self._upbit:
            return []

        def _fetch():
            return self._upbit.get_balances() or []

        return await asyncio.to_thread(_fetch)

    async def get_balance(self, ticker: str = "KRW") -> float:
        """특정 자산 잔고 조회. ticker: 'KRW', 'BTC', 'ETH' 등."""
        if not self._upbit:
            return 0.0

        def _fetch():
            return self._upbit.get_balance(ticker) or 0.0

        return await asyncio.to_thread(_fetch)

    # ── 주문 ──

    async def buy_market(self, market: str, price: float) -> dict:
        """시장가 매수 (KRW 금액 기준)."""
        if not self._upbit:
            logger.warning("업비트 인증 없음 — 매수 스킵: %s %s원", market, price)
            return {}

        def _order():
            return self._upbit.buy_market_order(market, price)

        result = await asyncio.to_thread(_order)
        logger.info("시장가 매수: %s %s원 → %s", market, price, result)
        return result or {}

    async def sell_market(self, market: str, volume: float) -> dict:
        """시장가 매도 (코인 수량 기준)."""
        if not self._upbit:
            logger.warning("업비트 인증 없음 — 매도 스킵: %s %.8f", market, volume)
            return {}

        def _order():
            return self._upbit.sell_market_order(market, volume)

        result = await asyncio.to_thread(_order)
        logger.info("시장가 매도: %s %.8f → %s", market, volume, result)
        return result or {}

    async def buy_limit(self, market: str, price: float, volume: float) -> dict:
        """지정가 매수."""
        if not self._upbit:
            return {}

        def _order():
            return self._upbit.buy_limit_order(market, price, volume)

        result = await asyncio.to_thread(_order)
        logger.info("지정가 매수: %s %s원 x %.8f → %s", market, price, volume, result)
        return result or {}

    async def sell_limit(self, market: str, price: float, volume: float) -> dict:
        """지정가 매도."""
        if not self._upbit:
            return {}

        def _order():
            return self._upbit.sell_limit_order(market, price, volume)

        result = await asyncio.to_thread(_order)
        logger.info("지정가 매도: %s %s원 x %.8f → %s", market, price, volume, result)
        return result or {}
