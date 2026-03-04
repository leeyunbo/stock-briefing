"""기술적 분석 — OHLCV 수집 + 기술적 지표 계산.

US: yfinance, KR: 네이버 금융 API.
pandas만으로 지표 계산 (추가 라이브러리 불필요).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from app.collector.kr_stock_research import (
    HEADERS,
    NAVER_CHART_API,
    NAVER_POLLING_API,
    NAVER_STOCK_API,
    resolve_kr_ticker,
)
from app.core.http import get_http_client

logger = logging.getLogger(__name__)


# ── 데이터 모델 ──


@dataclass
class TechnicalIndicators:
    """기술적 지표 전체 시계열 + 최신 스냅샷."""

    ticker: str
    name: str = ""
    market: str = "US"  # "US" / "KR"
    currency: str = "USD"

    # 시계열 (pandas Series / ndarray 형태로 저장)
    dates: list[str] = field(default_factory=list)
    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    volumes: list[int] = field(default_factory=list)

    # 이동평균
    sma20: list[float] = field(default_factory=list)
    sma50: list[float] = field(default_factory=list)
    sma200: list[float] = field(default_factory=list)

    # RSI
    rsi: list[float] = field(default_factory=list)

    # MACD
    macd_line: list[float] = field(default_factory=list)
    macd_signal: list[float] = field(default_factory=list)
    macd_histogram: list[float] = field(default_factory=list)

    # 볼린저밴드
    bb_upper: list[float] = field(default_factory=list)
    bb_middle: list[float] = field(default_factory=list)
    bb_lower: list[float] = field(default_factory=list)

    # 거래량 이동평균
    volume_sma20: list[float] = field(default_factory=list)

    # 지지/저항
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)

    # 최신 스냅샷
    latest_close: float = 0
    latest_change_pct: float = 0
    latest_volume: int = 0
    latest_rsi: float = 0
    latest_macd: float = 0
    latest_macd_signal: float = 0
    latest_macd_histogram: float = 0
    latest_bb_upper: float = 0
    latest_bb_lower: float = 0
    latest_bb_pct_b: float = 0  # %B = (close - lower) / (upper - lower)
    week52_high: float = 0
    week52_low: float = 0

    @property
    def latest_sma20(self) -> float:
        return self.sma20[-1] if self.sma20 else 0

    @property
    def latest_sma50(self) -> float:
        return self.sma50[-1] if self.sma50 else 0

    @property
    def latest_sma200(self) -> float:
        return self.sma200[-1] if self.sma200 else 0


# ── OHLCV 수집 ──


def fetch_ohlcv_us(ticker: str) -> pd.DataFrame:
    """yfinance로 US 종목 1년 일봉을 수집한다."""
    t = yf.Ticker(ticker)
    df = t.history(period="1y")
    if df.empty:
        raise ValueError(f"US OHLCV 데이터 없음: {ticker}")
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


async def fetch_ohlcv_kr(code: str) -> pd.DataFrame:
    """네이버 금융 API로 KR 종목 1년 일봉을 수집한다."""
    import httpx

    today = datetime.now()
    start = (today - timedelta(days=365)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        resp = await client.get(
            f"{NAVER_CHART_API}/{code}/day",
            params={"startDateTime": start, "endDateTime": end},
        )
        resp.raise_for_status()
        data = resp.json()
        prices = data if isinstance(data, list) else data.get("priceInfos", [])

    if not prices:
        raise ValueError(f"KR OHLCV 데이터 없음: {code}")

    rows = []
    for p in prices:
        try:
            rows.append({
                "date": pd.to_datetime(p.get("localDate", p.get("date", ""))),
                "open": float(p.get("openPrice", 0)),
                "high": float(p.get("highPrice", 0)),
                "low": float(p.get("lowPrice", 0)),
                "close": float(p.get("closePrice", 0)),
                "volume": int(p.get("accumulatedTradingVolume", 0)),
            })
        except (ValueError, TypeError):
            continue

    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


async def fetch_kr_name(code: str) -> str:
    """네이버 API에서 KR 종목명을 가져온다."""
    try:
        client = get_http_client()
        resp = await client.get(
            f"{NAVER_STOCK_API}/stock/{code}/basic",
            headers=HEADERS,
        )
        resp.raise_for_status()
        return resp.json().get("stockName", code)
    except Exception:
        return code


async def fetch_kr_current_price(code: str) -> tuple[float, float]:
    """KR 종목 현재가 + 등락률을 가져온다."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
            resp = await client.get(f"{NAVER_POLLING_API}/{code}")
            resp.raise_for_status()
            d = resp.json()["datas"][0]
            current = float(str(d.get("closePrice", "0")).replace(",", ""))
            change_pct = float(str(d.get("fluctuationsRatio", "0")).replace(",", ""))
            return current, change_pct
    except Exception:
        return 0, 0


# ── 지표 계산 ──


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothing RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _find_pivot_levels(highs: pd.Series, lows: pd.Series, closes: pd.Series) -> tuple[list[float], list[float]]:
    """최근 피봇 포인트 + 52주 고/저로 지지/저항 레벨을 구한다."""
    support = []
    resistance = []

    week52_high = float(highs.max())
    week52_low = float(lows.min())
    latest_close = float(closes.iloc[-1])

    # 피봇 포인트 (최근 데이터 기준)
    h = float(highs.iloc[-1])
    l = float(lows.iloc[-1])
    c = float(closes.iloc[-1])
    pivot = (h + l + c) / 3

    r1 = 2 * pivot - l
    r2 = pivot + (h - l)
    s1 = 2 * pivot - h
    s2 = pivot - (h - l)

    # 최근 20일 저점들 (지지), 고점들 (저항) 찾기
    window = min(20, len(lows))
    recent_lows = lows.iloc[-window:]
    recent_highs = highs.iloc[-window:]

    # 로컬 최저점 (3일 윈도우)
    for i in range(1, len(recent_lows) - 1):
        if recent_lows.iloc[i] <= recent_lows.iloc[i - 1] and recent_lows.iloc[i] <= recent_lows.iloc[i + 1]:
            if recent_lows.iloc[i] < latest_close:
                support.append(float(recent_lows.iloc[i]))

    # 로컬 최고점
    for i in range(1, len(recent_highs) - 1):
        if recent_highs.iloc[i] >= recent_highs.iloc[i - 1] and recent_highs.iloc[i] >= recent_highs.iloc[i + 1]:
            if recent_highs.iloc[i] > latest_close:
                resistance.append(float(recent_highs.iloc[i]))

    # 피봇 레벨 + 52주 고/저 추가
    support.extend([s1, s2, week52_low])
    resistance.extend([r1, r2, week52_high])

    # 현재가 기준 정렬, 중복 제거
    support = sorted(set(round(s, 2) for s in support if s < latest_close), reverse=True)[:3]
    resistance = sorted(set(round(r, 2) for r in resistance if r > latest_close))[:3]

    return support, resistance


def calculate_indicators(df: pd.DataFrame, ticker: str, market: str) -> TechnicalIndicators:
    """DataFrame에서 기술적 지표를 계산한다."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # 이동평균
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    # EMA (MACD용)
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()

    # MACD
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9).mean()
    macd_histogram = macd_line - macd_signal

    # RSI
    rsi = _calc_rsi(close, 14)

    # 볼린저밴드
    bb_middle = sma20
    bb_std = close.rolling(20).std()
    bb_upper = bb_middle + 2 * bb_std
    bb_lower = bb_middle - 2 * bb_std

    # 거래량 이동평균
    vol_sma20 = volume.rolling(20).mean()

    # 지지/저항
    support, resistance = _find_pivot_levels(high, low, close)

    # NaN → 0 변환 헬퍼
    def to_list(s: pd.Series) -> list:
        return [0 if pd.isna(v) else round(float(v), 4) for v in s]

    def to_int_list(s: pd.Series) -> list:
        return [0 if pd.isna(v) else int(v) for v in s]

    # 최신값
    latest_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else latest_close
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else 0

    latest_bb_upper = float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else 0
    latest_bb_lower = float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else 0
    bb_width = latest_bb_upper - latest_bb_lower
    bb_pct_b = ((latest_close - latest_bb_lower) / bb_width * 100) if bb_width > 0 else 50

    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df.index]

    ind = TechnicalIndicators(
        ticker=ticker,
        market=market,
        currency="KRW" if market == "KR" else "USD",
        dates=dates,
        opens=to_list(df["open"]),
        highs=to_list(high),
        lows=to_list(low),
        closes=to_list(close),
        volumes=to_int_list(volume),
        sma20=to_list(sma20),
        sma50=to_list(sma50),
        sma200=to_list(sma200),
        rsi=to_list(rsi),
        macd_line=to_list(macd_line),
        macd_signal=to_list(macd_signal),
        macd_histogram=to_list(macd_histogram),
        bb_upper=to_list(bb_upper),
        bb_middle=to_list(bb_middle),
        bb_lower=to_list(bb_lower),
        volume_sma20=to_list(vol_sma20),
        support_levels=support,
        resistance_levels=resistance,
        latest_close=round(latest_close, 2),
        latest_change_pct=round(change_pct, 2),
        latest_volume=int(volume.iloc[-1]),
        latest_rsi=round(float(rsi.iloc[-1]), 2) if not pd.isna(rsi.iloc[-1]) else 0,
        latest_macd=round(float(macd_line.iloc[-1]), 4) if not pd.isna(macd_line.iloc[-1]) else 0,
        latest_macd_signal=round(float(macd_signal.iloc[-1]), 4) if not pd.isna(macd_signal.iloc[-1]) else 0,
        latest_macd_histogram=round(float(macd_histogram.iloc[-1]), 4) if not pd.isna(macd_histogram.iloc[-1]) else 0,
        latest_bb_upper=round(latest_bb_upper, 2),
        latest_bb_lower=round(latest_bb_lower, 2),
        latest_bb_pct_b=round(bb_pct_b, 2),
        week52_high=round(float(high.max()), 2),
        week52_low=round(float(low.min()), 2),
    )

    return ind
