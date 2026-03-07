"""기술적 지표 계산 — pandas-ta 기반."""

import logging
from dataclasses import dataclass

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


@dataclass
class TechnicalIndicators:
    """단일 종목의 기술적 지표 스냅샷."""

    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    volume_ratio: float | None = None  # 현재 거래량 / 20일 평균
    atr_14: float | None = None


def calculate_indicators(candles_df: pd.DataFrame) -> TechnicalIndicators:
    """캔들 DataFrame에서 기술적 지표를 계산한다.

    candles_df 컬럼: datetime, open, high, low, close, volume
    최소 200행 이상 권장 (SMA 200 계산용).
    """
    if candles_df.empty or len(candles_df) < 14:
        logger.warning("캔들 데이터 부족 (%d행) — 빈 지표 반환", len(candles_df))
        return TechnicalIndicators()

    df = candles_df.copy()
    indicators = TechnicalIndicators()

    # RSI (14)
    rsi = ta.rsi(df["close"], length=14)
    if rsi is not None and not rsi.empty:
        indicators.rsi_14 = _last(rsi)

    # MACD (12, 26, 9)
    macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        indicators.macd = _last(macd_df.iloc[:, 0])
        indicators.macd_signal = _last(macd_df.iloc[:, 1])
        indicators.macd_histogram = _last(macd_df.iloc[:, 2])

    # 볼린저 밴드 (20, 2)
    bb_df = ta.bbands(df["close"], length=20, std=2)
    if bb_df is not None and not bb_df.empty:
        indicators.bb_lower = _last(bb_df.iloc[:, 0])
        indicators.bb_middle = _last(bb_df.iloc[:, 1])
        indicators.bb_upper = _last(bb_df.iloc[:, 2])

    # SMA
    for period, attr in [(20, "sma_20"), (50, "sma_50"), (200, "sma_200")]:
        if len(df) >= period:
            sma = ta.sma(df["close"], length=period)
            if sma is not None and not sma.empty:
                setattr(indicators, attr, _last(sma))

    # EMA
    for period, attr in [(12, "ema_12"), (26, "ema_26")]:
        ema = ta.ema(df["close"], length=period)
        if ema is not None and not ema.empty:
            setattr(indicators, attr, _last(ema))

    # Volume Ratio (현재 거래량 / 20일 평균)
    if len(df) >= 20 and "volume" in df.columns:
        vol_avg = df["volume"].rolling(20).mean()
        if vol_avg is not None and not vol_avg.empty:
            avg = _last(vol_avg)
            cur = df["volume"].iloc[-1]
            if avg and avg > 0:
                indicators.volume_ratio = round(cur / avg, 2)

    # ATR (14)
    atr = ta.atr(df["high"], df["low"], df["close"], length=14)
    if atr is not None and not atr.empty:
        indicators.atr_14 = _last(atr)

    return indicators


def _last(series: pd.Series) -> float | None:
    """Series의 마지막 유효값을 반환한다."""
    if series is None or series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return round(float(val), 4)
