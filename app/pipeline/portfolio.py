"""AI 포트폴리오 일일 관리 파이프라인.

Day 1: NASDAQ 100에서 10~15종목 최초 구성
Day N: 일일 리뷰 — KEEP/ADD/REMOVE/REWEIGHT
매일 이메일로 포트폴리오 현황 + P&L + 변경사항 발송.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.collector.crypto import screen_crypto
from app.collector.market_scan import NASDAQ_100, fetch_macro_indicators, scan_market
from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.collector.stock_research import screen_candidates
from app.core.database import async_session
from app.core.models import (
    BriefingType,
    PortfolioChangeLog,
    PortfolioDailySnapshot,
    PortfolioHolding,
    Subscriber,
)
from app.pipeline.base import PipelineContext, run_steps
from app.prompts.portfolio import PortfolioDecisions, call_portfolio_llm
from app.publishing.email_sender import send_briefing_to_subscribers
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


# ── 데이터클래스 ──


@dataclass
class PnlRow:
    ticker: str
    name: str
    weight_pct: float
    entry_price: float
    current_price: float
    return_pct: float
    contribution_pct: float


# ── 파이프라인 컨텍스트 ──


class PortfolioContext(PipelineContext, total=False):
    holdings: list[PortfolioHolding]
    macro: MacroIndicators
    scan: MarketScanData
    candidates: list[CandidateScreenData]
    decisions: PortfolioDecisions
    pnl: list[PnlRow]
    total_return_pct: float
    cash_weight_pct: float
    day_number: int


# ── Step 1: DB에서 현재 포트폴리오 로드 ──


async def load_portfolio(ctx: PortfolioContext) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(PortfolioHolding).where(PortfolioHolding.is_active.is_(True))
        )
        holdings = list(result.scalars().all())

    ctx["holdings"] = holdings
    is_day1 = len(holdings) == 0
    ctx["day_number"] = 1 if is_day1 else _compute_day(holdings)
    logger.info("포트폴리오 로드: %d종목, Day %d", len(holdings), ctx["day_number"])


def _compute_day(holdings: list[PortfolioHolding]) -> int:
    if not holdings:
        return 1
    earliest = min(h.entry_date for h in holdings)
    return (date.today() - earliest).days + 1


# ── Step 2: 매크로 + 시장 스캔 (병렬) ──


async def collect_data(ctx: PortfolioContext) -> None:
    scan_result, macro_result = await asyncio.gather(
        scan_market(),
        fetch_macro_indicators(),
        return_exceptions=True,
    )
    ctx["scan"] = scan_result if not isinstance(scan_result, BaseException) else MarketScanData()
    ctx["macro"] = macro_result if not isinstance(macro_result, BaseException) else MacroIndicators()

    if isinstance(scan_result, BaseException):
        logger.error("마켓 스캔 실패: %s", scan_result)
    if isinstance(macro_result, BaseException):
        logger.error("매크로 지표 실패: %s", macro_result)


# ── Step 3: 후보 종목 스크리닝 ──


async def screen_stocks(ctx: PortfolioContext) -> None:
    # 보유 종목 티커 추가 (NASDAQ_100에 없을 수 있음)
    holding_tickers = {h.ticker for h in ctx.get("holdings", [])}
    universe = list(dict.fromkeys(NASDAQ_100 + list(holding_tickers)))

    # 주식 + 코인 병렬 스크리닝
    stock_candidates, crypto_candidates = await asyncio.gather(
        screen_candidates(universe),
        screen_crypto(),
        return_exceptions=True,
    )

    candidates: list[CandidateScreenData] = []
    if not isinstance(stock_candidates, BaseException):
        candidates.extend(stock_candidates)
    else:
        logger.error("주식 스크리닝 실패: %s", stock_candidates)
    if not isinstance(crypto_candidates, BaseException):
        candidates.extend(crypto_candidates)
    else:
        logger.error("코인 스크리닝 실패: %s", crypto_candidates)

    ctx["candidates"] = candidates
    logger.info("후보 스크리닝 완료: %d종목 (주식+코인)", len(ctx["candidates"]))


# ── Step 4: LLM 포트폴리오 결정 ──


async def generate_decisions(ctx: PortfolioContext) -> None:
    ctx["decisions"] = await call_portfolio_llm(
        holdings=ctx.get("holdings", []),
        candidates=ctx.get("candidates", []),
        macro=ctx.get("macro", MacroIndicators()),
        scan=ctx.get("scan", MarketScanData()),
        run_id=ctx.get("run_id", ""),
    )


# ── Step 5: P&L 계산 ──


async def calculate_pnl(ctx: PortfolioContext) -> None:
    decisions = ctx.get("decisions")
    if not decisions:
        return

    # 후보 데이터에서 현재가 조회
    price_map: dict[str, float] = {}
    for c in ctx.get("candidates", []):
        if c.close > 0:
            price_map[c.ticker] = c.close

    # 기존 보유 종목의 편입가
    entry_map: dict[str, float] = {}
    for h in ctx.get("holdings", []):
        entry_map[h.ticker] = h.entry_price

    pnl_rows: list[PnlRow] = []
    for d in decisions.decisions:
        if d.action == "REMOVE":
            continue

        current_price = price_map.get(d.ticker, 0)
        entry_price = entry_map.get(d.ticker, current_price)  # 신규 ADD는 현재가가 편입가
        return_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
        contribution_pct = d.new_weight_pct * return_pct / 100

        pnl_rows.append(PnlRow(
            ticker=d.ticker,
            name=d.name,
            weight_pct=d.new_weight_pct,
            entry_price=round(entry_price, 2),
            current_price=round(current_price, 2),
            return_pct=round(return_pct, 2),
            contribution_pct=round(contribution_pct, 2),
        ))

    total_return = sum(r.contribution_pct for r in pnl_rows)
    cash_pct = decisions.cash_weight_pct
    ctx["pnl"] = pnl_rows
    ctx["total_return_pct"] = round(total_return, 2)
    ctx["cash_weight_pct"] = cash_pct
    logger.info("P&L 계산 완료: 누적 수익률 %.2f%%, 현금 비중 %.1f%%", total_return, cash_pct)


# ── Step 6: DB 저장 ──


async def save_portfolio(ctx: PortfolioContext) -> None:
    decisions = ctx.get("decisions")
    if not decisions:
        return

    today = date.today()
    run_id = ctx.get("run_id", "")
    pnl_rows = ctx.get("pnl", [])

    # 현재가/편입가 맵
    price_map: dict[str, float] = {r.ticker: r.current_price for r in pnl_rows}
    entry_map: dict[str, float] = {r.ticker: r.entry_price for r in pnl_rows}

    # 후보 데이터에서 industry/name 조회
    candidate_map: dict[str, CandidateScreenData] = {
        c.ticker: c for c in ctx.get("candidates", [])
    }

    async with async_session() as db:
        # 기존 홀딩 로드
        result = await db.execute(
            select(PortfolioHolding).where(PortfolioHolding.is_active.is_(True))
        )
        existing = {h.ticker: h for h in result.scalars().all()}

        for d in decisions.decisions:
            if d.action == "REMOVE":
                # 비활성화
                if d.ticker in existing:
                    existing[d.ticker].is_active = False
                # 변경 로그
                db.add(PortfolioChangeLog(
                    change_date=today, action="REMOVE", ticker=d.ticker,
                    old_weight_pct=existing[d.ticker].weight_pct if d.ticker in existing else None,
                    new_weight_pct=0, reason=d.reason, run_id=run_id,
                ))
            elif d.action == "ADD":
                current_price = price_map.get(d.ticker, 0)
                cand = candidate_map.get(d.ticker)
                db.add(PortfolioHolding(
                    ticker=d.ticker,
                    name=d.name or (cand.name if cand else ""),
                    industry=cand.industry if cand else "",
                    weight_pct=d.new_weight_pct,
                    entry_price=current_price,
                    entry_date=today,
                    is_active=True,
                ))
                db.add(PortfolioChangeLog(
                    change_date=today, action="ADD", ticker=d.ticker,
                    old_weight_pct=None, new_weight_pct=d.new_weight_pct,
                    reason=d.reason, run_id=run_id,
                ))
            elif d.action in ("KEEP", "REWEIGHT"):
                if d.ticker in existing:
                    old_weight = existing[d.ticker].weight_pct
                    existing[d.ticker].weight_pct = d.new_weight_pct
                    if d.action == "REWEIGHT":
                        db.add(PortfolioChangeLog(
                            change_date=today, action="REWEIGHT", ticker=d.ticker,
                            old_weight_pct=old_weight, new_weight_pct=d.new_weight_pct,
                            reason=d.reason, run_id=run_id,
                        ))

        # 일일 스냅샷 저장 (UPSERT — 같은 날 재실행 시 업데이트)
        for r in pnl_rows:
            stmt = sqlite_insert(PortfolioDailySnapshot).values(
                snapshot_date=today,
                ticker=r.ticker,
                current_price=r.current_price,
                entry_price=r.entry_price,
                weight_pct=r.weight_pct,
                return_pct=r.return_pct,
                contribution_pct=r.contribution_pct,
            ).on_conflict_do_update(
                index_elements=["snapshot_date", "ticker"],
                set_={
                    "current_price": r.current_price,
                    "weight_pct": r.weight_pct,
                    "return_pct": r.return_pct,
                    "contribution_pct": r.contribution_pct,
                },
            )
            await db.execute(stmt)

        await db.commit()

    logger.info("포트폴리오 DB 저장 완료 (run_id=%s)", run_id)


# ── Step 7: 이메일 발송 ──


async def send_portfolio_email(ctx: PortfolioContext) -> None:
    email_to: list[str] | None = ctx.get("email_to")
    decisions = ctx.get("decisions")
    if not decisions:
        return

    # 수신자 결정
    if email_to is not None:
        if not email_to:
            logger.info("이메일 발송 건너뜀 (빈 리스트)")
            return
        recipients = email_to
    else:
        async with async_session() as db:
            rows = await db.execute(select(Subscriber.email).where(Subscriber.is_active.is_(True)))
            recipients = [row[0] for row in rows.all()]

    if not recipients:
        logger.info("구독자 없음 — 이메일 발송 건너뜀")
        return

    # 변경 사항 필터
    changes = [d for d in decisions.decisions if d.action in ("ADD", "REMOVE", "REWEIGHT")]

    # Jinja2 렌더링
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    template = env.get_template("email_portfolio.html")
    html = template.render(
        day_number=ctx.get("day_number", 1),
        date_str=date.today().strftime("%Y년 %m월 %d일"),
        total_return_pct=ctx.get("total_return_pct", 0),
        cash_weight_pct=ctx.get("cash_weight_pct", 0),
        market_view=decisions.market_view,
        pnl=ctx.get("pnl", []),
        changes=changes,
    )

    subject = f"[Moneydive] AI 포트폴리오 Day {ctx.get('day_number', 1)} ({date.today().strftime('%m/%d')})"
    send_result = await send_briefing_to_subscribers(recipients, subject, html)
    logger.info("포트폴리오 이메일 발송: 성공 %d, 실패 %d", send_result["success"], send_result["fail"])


# ── 파이프라인 실행 ──


PORTFOLIO_STEPS = [
    load_portfolio,
    collect_data,
    screen_stocks,
    generate_decisions,
    calculate_pnl,
    save_portfolio,
    send_portfolio_email,
]


PORTFOLIO_DEFAULT_RECIPIENTS = ["servers1@naver.com"]


async def run_portfolio_pipeline(email_to: list[str] | None = PORTFOLIO_DEFAULT_RECIPIENTS) -> str:
    """AI 포트폴리오 파이프라인을 실행한다."""
    run_id = generate_run_id()
    logger.info("포트폴리오 파이프라인 시작 (run_id=%s, date=%s)", run_id, date.today())

    ctx: PortfolioContext = {
        "run_id": run_id,
        "email_to": email_to,
        "pipeline": "portfolio",
        "briefing_type": BriefingType.PORTFOLIO,
    }

    await run_steps(PORTFOLIO_STEPS, ctx)

    day_number = ctx.get("day_number", 1)
    total_return = ctx.get("total_return_pct", 0)
    logger.info("포트폴리오 파이프라인 완료: Day %d, 누적 수익률 %.2f%%", day_number, total_return)
    return run_id
