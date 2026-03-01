"""주식 리서치 파이프라인 — 두 가지 모드.

Mode A (기본): 뉴스 딥다이브 — 시장 코멘터리
  collect → holiday → dedup → analyze → screen → clear → report → deliver

Mode B (--ticker): 개별 종목 딥리서치
  fetch → summarize → deliver
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.market_scan import fetch_macro_indicators, scan_market
from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.collector.stock_research import fetch_stock_research, screen_candidates
from app.core.models import BriefingType
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.prompts.news_dive import analyze_news, generate_news_dive_report
from app.prompts.deep_research import summarize_research
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class NewsDiveContext(PipelineContext, total=False):
    """뉴스 딥다이브 파이프라인 컨텍스트."""

    scan: MarketScanData
    macro: MacroIndicators
    is_market_day: bool
    analysis: dict[str, Any]
    mentioned_tickers: list[str]
    screened: list[CandidateScreenData]


# ══════════════════════════════════════════════
# Mode A: 뉴스 딥다이브
# ══════════════════════════════════════════════


def _extract_mentioned_tickers(analysis: dict) -> list[str]:
    """뉴스 분석 결과에서 중복 없이 티커를 추출한다."""
    tickers = []
    seen = set()
    for story in analysis.get("stories", []):
        for key in ["affected_tickers", "beneficiary_tickers"]:
            for t in story.get(key, []):
                t = t.upper().strip()
                if t and t not in seen:
                    tickers.append(t)
                    seen.add(t)
    return tickers


# ── 스텝 함수 ──


async def collect_market_data(ctx: NewsDiveContext) -> None:
    """Stage 1: 시장 스캔 + 매크로 지표를 병렬 수집한다."""
    logger.info("[Stage 1] 시장 스캔 + 매크로 지표 수집...")
    scan_data, macro_data = await asyncio.gather(scan_market(), fetch_macro_indicators())
    logger.info("[Stage 1] 스캔 완료: 뉴스 %d건, 매크로 VIX=%s",
                len(scan_data.market_news), macro_data.vix)
    ctx["scan"] = scan_data
    ctx["macro"] = macro_data


async def skip_prices_if_holiday(ctx: NewsDiveContext) -> None:
    """휴장일이면 개별 종목 시세 데이터를 비운다."""
    is_market_day = date.today().weekday() < 5
    ctx["is_market_day"] = is_market_day
    if not is_market_day:
        logger.info("휴장일 — 개별 종목 시세 데이터 제외")
        scan = ctx["scan"]
        scan.scan_date += " (미국 증시 휴장일)"
        scan.top_gainers = []
        scan.top_losers = []
        scan.top_volume = []
        scan.earnings_today = []
        scan.earnings_tomorrow = []


async def dedup_market_news(ctx: NewsDiveContext) -> None:
    """시맨틱 중복 제거 + trace."""
    from app.collector.dedup import dedup_news
    scan = ctx["scan"]
    scan.market_news = dedup_news(
        scan.market_news, lambda n: f"{n.headline} {n.summary}",
        "market_news", run_id=ctx["run_id"], pipeline="news_dive",
    )
    if not scan.market_news:
        logger.info("새로운 뉴스 없음 — 파이프라인 스킵")
        ctx["skip"] = True


async def analyze_market_news(ctx: NewsDiveContext) -> None:
    """Stage 2: Claude에게 핵심 이슈 + 관련 종목을 도출한다."""
    logger.info("[Stage 2] 뉴스 분석 중...")
    analysis = await to_thread(analyze_news, ctx["scan"], ctx["macro"], run_id=ctx["run_id"])
    mentioned_tickers = _extract_mentioned_tickers(analysis)
    logger.info("[Stage 2] 이슈 %d개, 언급 종목 %d개",
                len(analysis.get("stories", [])), len(mentioned_tickers))
    ctx["analysis"] = analysis
    ctx["mentioned_tickers"] = mentioned_tickers


async def screen_tickers(ctx: NewsDiveContext) -> None:
    """Stage 3: 언급 종목의 재무지표를 스크리닝한다."""
    tickers = ctx["mentioned_tickers"]
    logger.info("[Stage 3] %d개 종목 재무 스크리닝...", len(tickers))
    screened = await screen_candidates(tickers)
    logger.info("[Stage 3] 스크리닝 완료: %d개 종목 데이터 확보", len(screened))
    ctx["screened"] = screened


async def clear_stale_prices(ctx: NewsDiveContext) -> None:
    """휴장일이면 스크리닝 종목의 시세를 초기화한다."""
    if not ctx.get("is_market_day", True):
        for s in ctx["screened"]:
            s.close = 0
            s.change_pct_1d = 0


async def generate_dive_report(ctx: NewsDiveContext) -> None:
    """Stage 4: 뉴스 분석 + 재무지표 + 매크로로 최종 리포트를 생성한다."""
    logger.info("[Stage 4] 뉴스 딥다이브 리포트 작성 중...")
    result = await to_thread(
        generate_news_dive_report,
        ctx["analysis"], ctx["screened"], ctx["scan"], ctx["macro"],
        run_id=ctx["run_id"],
    )
    ctx["result"] = result


NEWS_DIVE_STEPS = [
    collect_market_data,
    skip_prices_if_holiday,
    dedup_market_news,
    analyze_market_news,
    screen_tickers,
    clear_stale_prices,
    generate_dive_report,
    deliver,
]


async def run_news_dive_pipeline(email_to: list[str] | None = None) -> str:
    """뉴스 딥다이브 파이프라인 — 스텝 기반."""
    logger.info("뉴스 딥다이브 파이프라인 시작: %s", date.today())
    ctx: NewsDiveContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "news_dive",
        "briefing_type": BriefingType.NEWS_DIVE,
    }
    await run_steps(NEWS_DIVE_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""


# ══════════════════════════════════════════════
# Mode B: 개별 종목 딥리서치
# ══════════════════════════════════════════════


async def run_deep_research_pipeline(ticker: str, email_to: list[str] | None = None) -> str:
    """개별 종목 딥리서치 파이프라인."""
    logger.info("딥리서치 파이프라인 시작: %s", ticker)

    data = await fetch_stock_research(ticker)
    result = await to_thread(summarize_research, data, run_id=generate_run_id())

    ctx: PipelineContext = {
        "result": result,
        "briefing_type": f"research_{ticker.lower()}",
        "email_to": email_to,
    }
    await deliver(ctx)

    return result.html
