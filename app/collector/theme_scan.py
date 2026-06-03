"""개인 아침 브리핑(중장기) — 매크로 + 레이더 + 테마 시세 + 발굴 후보.

WebSearch 대신 구조화 데이터(yfinance, market_scan)만 사용.
'핫 종목' 대신 중장기 관점의 '밸류 눌림목'과 '레이더 thesis 이벤트'를 골라낸다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.collector.market_scan import fetch_macro_indicators
from app.collector.news import NewsArticle, fetch_news, fetch_news_for_stocks
from app.collector.research_models import MacroIndicators
from app.collector.themes import THEMES, WATCHLIST, _names, all_tickers

logger = logging.getLogger(__name__)


@dataclass
class StockQuote:
    """개별 종목 시세 + 밸류 위치."""

    ticker: str
    name: str
    close: float = 0
    change_pct: float = 0
    volume: int = 0
    year_high: float = 0
    year_low: float = 0

    @property
    def pct_off_high(self) -> float:
        """52주 고점 대비 하락폭(%). 클수록 더 눌린 상태."""
        if self.year_high <= 0:
            return 0.0
        return round((self.year_high - self.close) / self.year_high * 100, 1)

    @property
    def pct_above_low(self) -> float:
        """52주 저점 대비 상승폭(%). 작을수록 저점 근처."""
        if self.year_low <= 0:
            return 0.0
        return round((self.close - self.year_low) / self.year_low * 100, 1)


@dataclass
class ThemeScanData:
    macro: MacroIndicators
    watchlist: list[StockQuote] = field(default_factory=list)
    themes: dict[str, list[StockQuote]] = field(default_factory=dict)
    spotlight: list[StockQuote] = field(default_factory=list)  # 깊게 볼 1~2종목
    value_picks: list[StockQuote] = field(default_factory=list)  # 발굴: 밸류 눌림목 상위
    market_news: list[NewsArticle] = field(default_factory=list)  # 시장 주요 뉴스
    radar_news: dict[str, list[NewsArticle]] = field(default_factory=dict)  # 레이더 종목별 뉴스


def _yf_quotes(tickers: list[str]) -> dict[str, tuple]:
    """yfinance 일괄 조회. ticker -> (종가, 등락%, 거래량, 52주고, 52주저)."""
    import yfinance as yf

    out: dict[str, tuple] = {}
    tk = yf.Tickers(" ".join(tickers))
    for sym in tickers:
        try:
            t = tk.tickers.get(sym)
            if not t:
                continue
            hist = t.history(period="5d")
            if hist.empty:
                continue
            close = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            change_pct = ((close - prev) / prev * 100) if prev != 0 else 0
            volume = int(hist["Volume"].iloc[-1])
            fi = t.fast_info
            year_high = float(getattr(fi, "year_high", 0) or 0)
            year_low = float(getattr(fi, "year_low", 0) or 0)
            out[sym] = (round(close, 2), round(change_pct, 2), volume, round(year_high, 2), round(year_low, 2))
        except Exception as e:
            logger.warning("시세 조회 에러 (%s): %s", sym, e)
    return out


async def scan_themes() -> ThemeScanData:
    """매크로 + 레이더 + 테마 시세를 모으고, 중장기 스포트라이트/발굴 후보를 선정한다."""
    watch_names = [name for _, name in WATCHLIST]
    macro, quotes, radar_news, market_news = await asyncio.gather(
        fetch_macro_indicators(),
        asyncio.to_thread(_yf_quotes, all_tickers()),
        fetch_news_for_stocks(watch_names),
        fetch_news("증시 시황 코스피 나스닥", 5),
        return_exceptions=True,
    )
    if isinstance(macro, BaseException):
        logger.error("매크로 수집 실패: %s", macro)
        macro = MacroIndicators()
    if isinstance(quotes, BaseException):
        logger.error("시세 수집 실패: %s", quotes)
        quotes = {}
    if isinstance(radar_news, BaseException):
        logger.warning("레이더 뉴스 수집 실패: %s", radar_news)
        radar_news = {}
    if isinstance(market_news, BaseException):
        logger.warning("시장 뉴스 수집 실패: %s", market_news)
        market_news = []

    names = _names()

    def mk(ticker: str) -> StockQuote | None:
        q = quotes.get(ticker)
        if not q:
            return None
        return StockQuote(ticker, names.get(ticker, ticker), *q)

    watchlist = [s for s in (mk(t) for t, _ in WATCHLIST) if s]

    themes_out: dict[str, list[StockQuote]] = {}
    for theme, pairs in THEMES.items():
        themes_out[theme] = [s for s in (mk(t) for t, _ in pairs) if s]

    # 발굴: 52주 고점 대비 많이 눌린 우량주 (중장기 밸류 기회). 레이더는 제외(이미 보고 있음).
    watch_tickers = {t for t, _ in WATCHLIST}
    universe: dict[str, StockQuote] = {}
    for lst in themes_out.values():
        for s in lst:
            universe.setdefault(s.ticker, s)
    value_picks = sorted(
        (s for s in universe.values() if s.ticker not in watch_tickers and s.year_high > 0),
        key=lambda s: s.pct_off_high,
        reverse=True,
    )[:3]

    # 스포트라이트: ① 레이더에 thesis 이벤트(당일 ±3% 이상) 있으면 우선,
    #             ② 없으면 발굴 후보 중 가장 눌린 1종목.
    spotlight: list[StockQuote] = []
    radar_events = sorted(watchlist, key=lambda s: abs(s.change_pct), reverse=True)
    if radar_events and abs(radar_events[0].change_pct) >= 3.0:
        spotlight.append(radar_events[0])
    if value_picks:
        for s in value_picks:
            if s.ticker not in {x.ticker for x in spotlight}:
                spotlight.append(s)
                break
    spotlight = spotlight[:2]

    logger.info(
        "스캔 완료: 레이더 %d, 테마 %d, 발굴 %s, 스포트라이트 %s",
        len(watchlist), len(themes_out),
        [s.ticker for s in value_picks], [s.ticker for s in spotlight],
    )
    return ThemeScanData(
        macro=macro, watchlist=watchlist, themes=themes_out,
        spotlight=spotlight, value_picks=value_picks,
        market_news=market_news[:5], radar_news=radar_news,
    )
