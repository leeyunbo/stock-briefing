"""코인 자동매매 파이프라인.

A. 15분 간격 — 규칙 기반 매매 (기술적 지표 → BUY/SELL)
B. 1시간 간격 — AI 전략 조정 (포지션 비중 재조정)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict

import pandas as pd
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import async_session
from app.pipeline.base import PipelineContext, run_steps
from app.prompts.crypto_trading import (
    CryptoStrategyResult,
    MarketDataForPrompt,
    call_crypto_strategy_llm,
)
from app.trading.indicators import TechnicalIndicators, calculate_indicators
from app.trading.models import CryptoPosition, CryptoSnapshot, CryptoTrade, StrategyState
from app.trading.signals import StrategyParams, TradeSignal, evaluate_signals
from app.trading.upbit_client import UpbitClient
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)

# ── 상수 ──

CRYPTO_UNIVERSE = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-POL",
]

INITIAL_CAPITAL = get_settings().upbit_initial_capital
MAX_DAILY_TRADES = 50
MIN_TRADE_INTERVAL_SEC = 300  # 같은 코인 5분 쿨다운
MAX_LOSS_PCT = -20.0  # 원금 대비 -20% → 봇 일시중지
MIN_ORDER_KRW = 5_000  # 업비트 최소 주문 금액


# ── 컨텍스트 ──


@dataclass
class MarketIndicators:
    """코인별 시장 데이터 + 지표."""

    market: str
    candles_df: pd.DataFrame
    indicators: TechnicalIndicators
    current_price: float = 0.0
    change_pct_24h: float = 0.0
    volume_24h: float = 0.0


class TradingContext(PipelineContext, total=False):
    client: UpbitClient
    market_data: list[MarketIndicators]
    signals: list[TradeSignal]
    strategy_params: StrategyParams
    positions: dict[str, CryptoPosition]  # market → position
    cash_krw: float
    total_asset_krw: float
    executed_trades: list[dict]
    strategy_result: CryptoStrategyResult
    daily_trade_count: int


# ══════════════════════════════════════
#  A. 15분 간격 — 규칙 기반 트레이딩
# ══════════════════════════════════════


async def init_client(ctx: TradingContext) -> None:
    """업비트 클라이언트 초기화 + 안전장치 확인."""
    ctx["client"] = UpbitClient()

    # 오늘 거래 횟수 확인
    today_start = datetime.combine(date.today(), datetime.min.time())
    async with async_session() as db:
        result = await db.execute(
            select(func.count(CryptoTrade.id)).where(CryptoTrade.trade_date >= today_start)
        )
        ctx["daily_trade_count"] = result.scalar() or 0

    if ctx["daily_trade_count"] >= MAX_DAILY_TRADES:
        logger.warning("일일 최대 거래 횟수(%d) 도달 — 트레이딩 중단", MAX_DAILY_TRADES)
        ctx["skip"] = True
        return

    # 총 손실 한도 확인 (현재 시장가 기준)
    client = ctx["client"]
    cash = await client.get_balance("KRW")
    balances = await client.get_balances()

    # 보유 코인 현재가 조회
    coin_markets = []
    coin_balances = []
    for b in balances:
        currency = b.get("currency", "")
        bal = float(b.get("balance", 0))
        if currency != "KRW" and bal > 0:
            coin_markets.append(f"KRW-{currency}")
            coin_balances.append((currency, bal))

    total = cash
    if coin_markets:
        tickers = await client.get_ticker(coin_markets)
        price_map = {}
        for t in tickers:
            if isinstance(t, dict):
                price_map[t.get("market", "")] = float(t.get("trade_price", 0))
        for currency, bal in coin_balances:
            market = f"KRW-{currency}"
            cur_price = price_map.get(market, 0)
            total += bal * cur_price

    ctx["cash_krw"] = cash
    ctx["total_asset_krw"] = total

    if total > 0:
        return_pct = (total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        if return_pct <= MAX_LOSS_PCT:
            logger.error("총 손실 한도(%.1f%%) 도달 — 봇 일시중지", return_pct)
            ctx["skip"] = True


async def fetch_candles(ctx: TradingContext) -> None:
    """업비트 캔들 데이터 수집 (15분봉 200개)."""
    client: UpbitClient = ctx["client"]
    market_data: list[MarketIndicators] = []

    for market in CRYPTO_UNIVERSE:
        try:
            candles = await client.get_candles(market, interval="minute15", count=200)
            if not candles:
                logger.warning("캔들 없음: %s", market)
                continue

            df = pd.DataFrame(candles)
            current_price = float(df["close"].iloc[-1]) if not df.empty else 0.0

            # 24시간 변동률 계산 (15분봉 96개 = 24시간)
            change_pct = 0.0
            if len(df) >= 96:
                old_price = float(df["close"].iloc[-96])
                if old_price > 0:
                    change_pct = (current_price - old_price) / old_price * 100

            volume_24h = float(df["volume"].tail(96).sum()) if len(df) >= 96 else float(df["volume"].sum())

            market_data.append(MarketIndicators(
                market=market,
                candles_df=df,
                indicators=TechnicalIndicators(),
                current_price=current_price,
                change_pct_24h=round(change_pct, 2),
                volume_24h=volume_24h,
            ))
        except Exception as e:
            logger.error("캔들 수집 실패 %s: %s", market, e)

    ctx["market_data"] = market_data
    logger.info("캔들 수집 완료: %d/%d 종목", len(market_data), len(CRYPTO_UNIVERSE))


async def calc_indicators(ctx: TradingContext) -> None:
    """기술적 지표 계산."""
    for md in ctx.get("market_data", []):
        try:
            md.indicators = calculate_indicators(md.candles_df)
        except Exception as e:
            logger.error("지표 계산 실패 %s: %s", md.market, e)


async def load_positions(ctx: TradingContext) -> None:
    """DB에서 현재 포지션 로드."""
    async with async_session() as db:
        result = await db.execute(
            select(CryptoPosition).where(CryptoPosition.is_active.is_(True))
        )
        positions = {p.market: p for p in result.scalars().all()}

    ctx["positions"] = positions

    # 최신 전략 파라미터 로드
    async with async_session() as db:
        result = await db.execute(
            select(StrategyState).order_by(StrategyState.id.desc()).limit(1)
        )
        state = result.scalar_one_or_none()

    if state:
        ctx["strategy_params"] = StrategyParams(
            mode=state.mode,
            rsi_buy_threshold=state.rsi_buy_threshold,
            rsi_sell_threshold=state.rsi_sell_threshold,
            max_position_pct=state.max_position_pct,
        )
    else:
        ctx["strategy_params"] = StrategyParams()

    logger.info("포지션 로드: %d종목, 전략 모드: %s", len(positions), ctx["strategy_params"].mode)


async def eval_signals(ctx: TradingContext) -> None:
    """매매 신호 판단."""
    positions = ctx.get("positions", {})
    params = ctx.get("strategy_params", StrategyParams())
    signals: list[TradeSignal] = []

    for md in ctx.get("market_data", []):
        # 현재 수익률 계산
        current_return = None
        if md.market in positions:
            pos = positions[md.market]
            if pos.avg_price > 0 and md.current_price > 0:
                current_return = (md.current_price - pos.avg_price) / pos.avg_price * 100

        signal = evaluate_signals(md.market, md.indicators, params, current_return)
        signals.append(signal)

        if signal.action != "HOLD":
            logger.info("신호: %s %s (강도 %.2f) — %s", signal.market, signal.action, signal.strength, signal.reasons)

    ctx["signals"] = signals


async def execute_trades(ctx: TradingContext) -> None:
    """주문 실행 (드라이런 또는 실제 매매)."""
    s = get_settings()
    client: UpbitClient = ctx["client"]
    signals = ctx.get("signals", [])
    positions = ctx.get("positions", {})
    params = ctx.get("strategy_params", StrategyParams())
    cash = ctx.get("cash_krw", 0.0)
    total = ctx.get("total_asset_krw", 0.0)
    executed: list[dict] = []
    daily_count = ctx.get("daily_trade_count", 0)

    # 최근 거래 시간 확인 (쿨다운)
    async with async_session() as db:
        cutoff = datetime.now(UTC) - timedelta(seconds=MIN_TRADE_INTERVAL_SEC)
        result = await db.execute(
            select(CryptoTrade.market).where(CryptoTrade.trade_date >= cutoff)
        )
        recent_markets = {row[0] for row in result.all()}

    for signal in signals:
        if signal.action == "HOLD":
            continue
        if daily_count >= MAX_DAILY_TRADES:
            logger.warning("일일 최대 거래 횟수 도달 — 중단")
            break
        if signal.market in recent_markets:
            logger.info("쿨다운 중: %s — 스킵", signal.market)
            continue

        max_order = total * (params.max_position_pct / 100)

        if signal.action == "BUY":
            # 매수 금액 = 강도에 비례, 최대 max_order
            order_krw = min(cash * 0.95, max_order) * signal.strength
            if order_krw < MIN_ORDER_KRW:
                logger.info("매수 금액 부족: %s %.0f원", signal.market, order_krw)
                continue

            trade_info = {
                "market": signal.market, "side": "BUY",
                "amount_krw": order_krw, "reasons": signal.reasons,
            }

            if s.upbit_trading_enabled:
                result = await client.buy_market(signal.market, order_krw)
                trade_info["order_result"] = result
                cash -= order_krw
            else:
                logger.info("[드라이런] 매수: %s %.0f원 — %s", signal.market, order_krw, signal.reasons)

            executed.append(trade_info)
            daily_count += 1

        elif signal.action == "SELL":
            if signal.market not in positions:
                continue
            pos = positions[signal.market]
            # 익절이면 50%만 매도, 아닌 경우 전량
            sell_ratio = params.take_profit_sell_ratio if "익절" in str(signal.reasons) else 1.0
            sell_qty = pos.quantity * sell_ratio

            trade_info = {
                "market": signal.market, "side": "SELL",
                "quantity": sell_qty, "reasons": signal.reasons,
            }

            if s.upbit_trading_enabled:
                result = await client.sell_market(signal.market, sell_qty)
                trade_info["order_result"] = result
            else:
                logger.info("[드라이런] 매도: %s %.8f — %s", signal.market, sell_qty, signal.reasons)

            executed.append(trade_info)
            daily_count += 1

    ctx["executed_trades"] = executed
    ctx["daily_trade_count"] = daily_count
    logger.info("주문 실행 완료: %d건", len(executed))


async def log_trades(ctx: TradingContext) -> None:
    """거래 로그를 DB에 저장하고 포지션을 업데이트한다."""
    executed = ctx.get("executed_trades", [])
    if not executed:
        return

    run_id = ctx.get("run_id", "")
    now = datetime.now(UTC)
    positions = ctx.get("positions", {})

    # 현재가 맵
    price_map = {md.market: md.current_price for md in ctx.get("market_data", [])}

    async with async_session() as db:
        for trade in executed:
            market = trade["market"]
            side = trade["side"]
            current_price = price_map.get(market, 0.0)

            if side == "BUY":
                amount_krw = trade["amount_krw"]
                qty = amount_krw / current_price if current_price > 0 else 0
                fee = amount_krw * 0.0005  # 업비트 수수료 0.05%

                db.add(CryptoTrade(
                    trade_date=now, market=market, side="BUY",
                    price=current_price, quantity=qty, amount_krw=amount_krw,
                    fee=fee, signal_type="RULE",
                    reason=", ".join(trade.get("reasons", [])), run_id=run_id,
                ))

                # 포지션 업데이트
                if market in positions:
                    pos = positions[market]
                    old_total = pos.avg_price * pos.quantity
                    new_total = old_total + amount_krw
                    pos.quantity += qty
                    pos.avg_price = new_total / pos.quantity if pos.quantity > 0 else 0
                    result = await db.execute(
                        select(CryptoPosition).where(
                            CryptoPosition.market == market, CryptoPosition.is_active.is_(True)
                        )
                    )
                    db_pos = result.scalar_one_or_none()
                    if db_pos:
                        db_pos.avg_price = pos.avg_price
                        db_pos.quantity = pos.quantity
                else:
                    db.add(CryptoPosition(
                        market=market, avg_price=current_price, quantity=qty, is_active=True,
                    ))

            elif side == "SELL":
                qty = trade["quantity"]
                amount_krw = qty * current_price
                fee = amount_krw * 0.0005

                db.add(CryptoTrade(
                    trade_date=now, market=market, side="SELL",
                    price=current_price, quantity=qty, amount_krw=amount_krw,
                    fee=fee, signal_type="RULE",
                    reason=", ".join(trade.get("reasons", [])), run_id=run_id,
                ))

                # 포지션 업데이트
                result = await db.execute(
                    select(CryptoPosition).where(
                        CryptoPosition.market == market, CryptoPosition.is_active.is_(True)
                    )
                )
                db_pos = result.scalar_one_or_none()
                if db_pos:
                    db_pos.quantity -= qty
                    if db_pos.quantity <= 0:
                        db_pos.is_active = False

        await db.commit()

    logger.info("거래 로그 저장 완료: %d건", len(executed))


# 15분 트레이딩 스텝
TRADING_STEPS = [
    init_client,
    fetch_candles,
    calc_indicators,
    load_positions,
    eval_signals,
    execute_trades,
    log_trades,
]


async def run_trading_pipeline() -> str:
    """15분 간격 규칙 기반 트레이딩 파이프라인."""
    run_id = generate_run_id()
    logger.info("코인 트레이딩 파이프라인 시작 (run_id=%s)", run_id)

    ctx: TradingContext = {
        "run_id": run_id,
        "pipeline": "crypto_trading",
        "briefing_type": "crypto_trading",
    }

    await run_steps(TRADING_STEPS, ctx)

    executed = ctx.get("executed_trades", [])
    logger.info("코인 트레이딩 완료: %d건 실행", len(executed))
    return run_id


# ══════════════════════════════════════
#  B. 1시간 간격 — AI 전략 조정
# ══════════════════════════════════════


async def ai_fetch_market_data(ctx: TradingContext) -> None:
    """AI 전략용 시장 데이터 수집 (1시간봉 기반)."""
    client: UpbitClient = ctx["client"]
    market_data: list[MarketIndicators] = []

    for market in CRYPTO_UNIVERSE:
        try:
            candles = await client.get_candles(market, interval="minute60", count=200)
            if not candles:
                continue
            df = pd.DataFrame(candles)
            indicators = calculate_indicators(df)
            current_price = float(df["close"].iloc[-1]) if not df.empty else 0.0

            change_pct = 0.0
            if len(df) >= 24:
                old = float(df["close"].iloc[-24])
                if old > 0:
                    change_pct = (current_price - old) / old * 100

            market_data.append(MarketIndicators(
                market=market, candles_df=df, indicators=indicators,
                current_price=current_price, change_pct_24h=round(change_pct, 2),
            ))
        except Exception as e:
            logger.error("AI 캔들 수집 실패 %s: %s", market, e)

    ctx["market_data"] = market_data


async def call_strategy_llm(ctx: TradingContext) -> None:
    """AI에게 전략 판단을 요청한다."""
    positions = ctx.get("positions", {})
    market_data = ctx.get("market_data", [])
    cash = ctx.get("cash_krw", 0.0)
    total = ctx.get("total_asset_krw", 0.0)
    current_mode = ctx.get("strategy_params", StrategyParams()).mode

    # 프롬프트용 데이터 구성
    prompt_data: list[MarketDataForPrompt] = []
    for md in market_data:
        pos = positions.get(md.market)
        return_pct = 0.0
        holding_qty = 0.0
        avg_price = 0.0
        if pos:
            holding_qty = pos.quantity
            avg_price = pos.avg_price
            if avg_price > 0:
                return_pct = (md.current_price - avg_price) / avg_price * 100

        prompt_data.append(MarketDataForPrompt(
            market=md.market,
            current_price=md.current_price,
            change_pct_24h=md.change_pct_24h,
            volume_24h=md.volume_24h,
            indicators=md.indicators,
            holding_qty=holding_qty,
            avg_price=avg_price,
            return_pct=return_pct,
        ))

    ctx["strategy_result"] = await call_crypto_strategy_llm(
        prompt_data, cash, total, current_mode, run_id=ctx.get("run_id", ""),
    )


async def apply_rebalance(ctx: TradingContext) -> None:
    """AI 결정에 따라 비중 재조정 주문을 실행한다."""
    s = get_settings()
    result = ctx.get("strategy_result")
    if not result or not result.decisions:
        return

    client: UpbitClient = ctx["client"]
    positions = ctx.get("positions", {})
    total = ctx.get("total_asset_krw", 0.0)
    cash = ctx.get("cash_krw", 0.0)
    price_map = {md.market: md.current_price for md in ctx.get("market_data", [])}
    run_id = ctx.get("run_id", "")
    now = datetime.now(UTC)

    async with async_session() as db:
        for decision in result.decisions:
            market = decision.market
            target_weight = decision.target_weight_pct
            current_price = price_map.get(market, 0.0)

            if current_price <= 0:
                continue

            target_value = total * (target_weight / 100)
            pos = positions.get(market)
            current_value = (pos.quantity * current_price) if pos else 0.0
            diff = target_value - current_value

            if decision.action == "SELL" and pos:
                # 전량 또는 일부 매도
                sell_qty = pos.quantity if target_weight == 0 else max(0, (current_value - target_value) / current_price)
                if sell_qty <= 0:
                    continue
                if s.upbit_trading_enabled:
                    await client.sell_market(market, sell_qty)
                else:
                    logger.info("[AI 드라이런] 매도: %s %.8f", market, sell_qty)

                amount_krw = sell_qty * current_price
                db.add(CryptoTrade(
                    trade_date=now, market=market, side="SELL",
                    price=current_price, quantity=sell_qty, amount_krw=amount_krw,
                    fee=amount_krw * 0.0005, signal_type="AI",
                    reason=decision.reason, run_id=run_id,
                ))

            elif decision.action == "BUY" and diff > MIN_ORDER_KRW:
                order_krw = min(diff, cash * 0.95, total * 0.2)
                if order_krw < MIN_ORDER_KRW:
                    continue
                if s.upbit_trading_enabled:
                    await client.buy_market(market, order_krw)
                else:
                    logger.info("[AI 드라이런] 매수: %s %.0f원", market, order_krw)

                qty = order_krw / current_price
                db.add(CryptoTrade(
                    trade_date=now, market=market, side="BUY",
                    price=current_price, quantity=qty, amount_krw=order_krw,
                    fee=order_krw * 0.0005, signal_type="AI",
                    reason=decision.reason, run_id=run_id,
                ))
                cash -= order_krw

            elif decision.action == "REWEIGHT" and pos:
                if diff > MIN_ORDER_KRW:
                    order_krw = min(diff, cash * 0.95)
                    if order_krw >= MIN_ORDER_KRW:
                        if s.upbit_trading_enabled:
                            await client.buy_market(market, order_krw)
                        else:
                            logger.info("[AI 드라이런] 리밸런스 매수: %s %.0f원", market, order_krw)
                        qty = order_krw / current_price
                        db.add(CryptoTrade(
                            trade_date=now, market=market, side="BUY",
                            price=current_price, quantity=qty, amount_krw=order_krw,
                            fee=order_krw * 0.0005, signal_type="AI",
                            reason=f"리밸런스: {decision.reason}", run_id=run_id,
                        ))
                        cash -= order_krw
                elif diff < -MIN_ORDER_KRW:
                    sell_qty = abs(diff) / current_price
                    if sell_qty > 0:
                        if s.upbit_trading_enabled:
                            await client.sell_market(market, sell_qty)
                        else:
                            logger.info("[AI 드라이런] 리밸런스 매도: %s %.8f", market, sell_qty)
                        amount_krw = sell_qty * current_price
                        db.add(CryptoTrade(
                            trade_date=now, market=market, side="SELL",
                            price=current_price, quantity=sell_qty, amount_krw=amount_krw,
                            fee=amount_krw * 0.0005, signal_type="AI",
                            reason=f"리밸런스: {decision.reason}", run_id=run_id,
                        ))

        # 전략 상태 저장
        db.add(StrategyState(
            mode=result.mode,
            max_position_pct=result.params.max_position_pct,
            rsi_buy_threshold=result.params.rsi_buy_threshold,
            rsi_sell_threshold=result.params.rsi_sell_threshold,
            params_json=json.dumps({
                "mode": result.mode,
                "rsi_buy_threshold": result.params.rsi_buy_threshold,
                "rsi_sell_threshold": result.params.rsi_sell_threshold,
                "max_position_pct": result.params.max_position_pct,
            }),
            ai_reasoning=result.market_view,
            run_id=run_id,
        ))

        await db.commit()

    logger.info("AI 리밸런스 완료: 모드=%s, %d종목 결정", result.mode, len(result.decisions))


async def save_snapshot(ctx: TradingContext) -> None:
    """일일 포트폴리오 스냅샷을 저장한다."""
    client: UpbitClient = ctx["client"]

    # 최신 잔고 재조회
    cash = await client.get_balance("KRW")
    balances = await client.get_balances()

    # 보유 코인 현재가 조회
    coin_items = []
    coin_markets = []
    for b in balances:
        currency = b.get("currency", "")
        if currency == "KRW":
            continue
        qty = float(b.get("balance", 0))
        avg_price = float(b.get("avg_buy_price", 0))
        if qty > 0:
            market = f"KRW-{currency}"
            coin_items.append((currency, market, qty, avg_price))
            coin_markets.append(market)

    price_map: dict[str, float] = {}
    if coin_markets:
        tickers = await client.get_ticker(coin_markets)
        for t in tickers:
            if isinstance(t, dict):
                price_map[t.get("market", "")] = float(t.get("trade_price", 0))

    positions_info = {}
    total_market_value = 0.0
    total_invested = 0.0
    for currency, market, qty, avg_price in coin_items:
        cur_price = price_map.get(market, avg_price)
        market_value = qty * cur_price
        cost_basis = qty * avg_price
        positions_info[market] = {
            "quantity": qty,
            "avg_price": avg_price,
            "current_price": cur_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "return_pct": round((cur_price - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0,
        }
        total_market_value += market_value
        total_invested += cost_basis

    total = cash + total_market_value
    return_pct = (total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100 if INITIAL_CAPITAL > 0 else 0

    today = date.today()
    async with async_session() as db:
        # 기존 스냅샷 업데이트 또는 생성
        result = await db.execute(
            select(CryptoSnapshot).where(CryptoSnapshot.snapshot_date == today)
        )
        snapshot = result.scalar_one_or_none()
        if snapshot:
            snapshot.total_krw = total
            snapshot.cash_krw = cash
            snapshot.invested_krw = total_invested
            snapshot.return_pct = round(return_pct, 2)
            snapshot.positions_json = json.dumps(positions_info, ensure_ascii=False)
        else:
            db.add(CryptoSnapshot(
                snapshot_date=today,
                total_krw=total,
                cash_krw=cash,
                invested_krw=total_invested,
                return_pct=round(return_pct, 2),
                positions_json=json.dumps(positions_info, ensure_ascii=False),
            ))
        await db.commit()

    logger.info("스냅샷 저장: 총자산 %.0f원, 현금 %.0f원, 수익률 %.2f%%", total, cash, return_pct)


# AI 전략 스텝
AI_STRATEGY_STEPS = [
    init_client,
    load_positions,
    ai_fetch_market_data,
    call_strategy_llm,
    apply_rebalance,
    save_snapshot,
]


async def run_ai_strategy_pipeline() -> str:
    """1시간 간격 AI 전략 파이프라인."""
    run_id = generate_run_id()
    logger.info("코인 AI 전략 파이프라인 시작 (run_id=%s)", run_id)

    ctx: TradingContext = {
        "run_id": run_id,
        "pipeline": "crypto_ai_strategy",
        "briefing_type": "crypto_ai_strategy",
    }

    await run_steps(AI_STRATEGY_STEPS, ctx)

    strategy = ctx.get("strategy_result")
    mode = strategy.mode if strategy else "unknown"
    logger.info("코인 AI 전략 완료: 모드=%s", mode)
    return run_id
