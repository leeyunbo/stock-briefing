"""규칙 기반 매매 신호 — 기술적 지표로 BUY/SELL/HOLD 판단."""

import logging
from dataclasses import dataclass, field

from app.trading.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


@dataclass
class StrategyParams:
    """AI가 조정 가능한 전략 파라미터."""

    mode: str = "moderate"  # aggressive / moderate / defensive
    rsi_buy_threshold: float = 30.0
    rsi_sell_threshold: float = 70.0
    bb_buy_enabled: bool = True
    bb_sell_enabled: bool = True
    macd_enabled: bool = True
    ma_trend_enabled: bool = True
    max_position_pct: float = 20.0  # 단일 코인 최대 비중
    stop_loss_pct: float = -7.0     # 손절 %
    take_profit_pct: float = 15.0   # 익절 %
    take_profit_sell_ratio: float = 0.5  # 익절 시 매도 비율


@dataclass
class TradeSignal:
    """매매 신호."""

    market: str           # "KRW-BTC"
    action: str           # "BUY", "SELL", "HOLD"
    strength: float       # 0.0~1.0
    reasons: list[str] = field(default_factory=list)


def evaluate_signals(
    market: str,
    indicators: TechnicalIndicators,
    params: StrategyParams,
    current_return_pct: float | None = None,
) -> TradeSignal:
    """기술적 지표 기반 매매 신호를 생성한다.

    current_return_pct: 현재 보유 중일 때 편입가 대비 수익률 (%)
    """
    buy_score = 0.0
    sell_score = 0.0
    reasons: list[str] = []

    # ── 손절/익절 (보유 포지션 있을 때) ──
    if current_return_pct is not None:
        if current_return_pct <= params.stop_loss_pct:
            return TradeSignal(
                market=market,
                action="SELL",
                strength=1.0,
                reasons=[f"손절: 수익률 {current_return_pct:.1f}% (기준 {params.stop_loss_pct}%)"],
            )
        if current_return_pct >= params.take_profit_pct:
            return TradeSignal(
                market=market,
                action="SELL",
                strength=0.8,
                reasons=[f"익절: 수익률 {current_return_pct:.1f}% (기준 {params.take_profit_pct}%)"],
            )

    # ── RSI ──
    if indicators.rsi_14 is not None:
        if indicators.rsi_14 < params.rsi_buy_threshold:
            score = min(1.0, (params.rsi_buy_threshold - indicators.rsi_14) / 20)
            buy_score += score * 0.3
            reasons.append(f"RSI 과매도({indicators.rsi_14:.1f})")
        elif indicators.rsi_14 > params.rsi_sell_threshold:
            score = min(1.0, (indicators.rsi_14 - params.rsi_sell_threshold) / 20)
            sell_score += score * 0.3
            reasons.append(f"RSI 과매수({indicators.rsi_14:.1f})")

    # ── MACD ──
    if params.macd_enabled and indicators.macd is not None and indicators.macd_signal is not None:
        if indicators.macd_histogram is not None:
            if indicators.macd > indicators.macd_signal and indicators.macd_histogram > 0:
                buy_score += 0.25
                reasons.append("MACD 골든크로스")
            elif indicators.macd < indicators.macd_signal and indicators.macd_histogram < 0:
                sell_score += 0.25
                reasons.append("MACD 데드크로스")

    # ── 볼린저 밴드 ──
    if indicators.bb_lower is not None and indicators.bb_upper is not None:
        close = indicators.sma_20  # bb_middle ≈ SMA 20
        if close is None:
            close = indicators.bb_middle
        if close is not None:
            if params.bb_buy_enabled and close <= indicators.bb_lower:
                buy_score += 0.25
                reasons.append(f"볼린저밴드 하단 터치({close:.0f} ≤ {indicators.bb_lower:.0f})")
            elif params.bb_sell_enabled and close >= indicators.bb_upper:
                sell_score += 0.25
                reasons.append(f"볼린저밴드 상단 터치({close:.0f} ≥ {indicators.bb_upper:.0f})")

    # ── 이동평균 정배열/역배열 ──
    if params.ma_trend_enabled and indicators.sma_20 is not None and indicators.sma_50 is not None:
        if indicators.sma_20 > indicators.sma_50:
            buy_score += 0.15
            reasons.append("이동평균 정배열(SMA20 > SMA50)")
        else:
            sell_score += 0.15
            reasons.append("이동평균 역배열(SMA20 < SMA50)")

    # ── 거래량 확인 ──
    if indicators.volume_ratio is not None and indicators.volume_ratio > 2.0:
        # 거래량 급증 → 기존 신호 강화
        if buy_score > sell_score:
            buy_score += 0.05
            reasons.append(f"거래량 급증({indicators.volume_ratio:.1f}x)")
        elif sell_score > buy_score:
            sell_score += 0.05
            reasons.append(f"거래량 급증({indicators.volume_ratio:.1f}x)")

    # ── 최종 판단 ──
    threshold = 0.3 if params.mode == "aggressive" else 0.4 if params.mode == "moderate" else 0.5

    if buy_score >= threshold and buy_score > sell_score:
        return TradeSignal(market=market, action="BUY", strength=min(1.0, buy_score), reasons=reasons)
    elif sell_score >= threshold and sell_score > buy_score:
        return TradeSignal(market=market, action="SELL", strength=min(1.0, sell_score), reasons=reasons)
    else:
        return TradeSignal(market=market, action="HOLD", strength=0.0, reasons=reasons or ["신호 없음"])
