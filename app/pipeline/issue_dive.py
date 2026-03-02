"""이슈 딥다이브 파이프라인 — 단일 이슈를 깊게 파는 피처 기사.

collect → dedup → pick_top_issue (LLM #1) → research_issue → generate_article (LLM #2) → deliver
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.market_scan import fetch_macro_indicators, scan_market
from app.collector.news import NewsArticle, fetch_news
from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.collector.stock_research import screen_candidates
from app.core.models import BriefingType
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.prompts.issue_dive import generate_issue_dive_article, pick_top_issue
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class IssueDiveContext(PipelineContext, total=False):
    """이슈 딥다이브 파이프라인 컨텍스트."""

    scan: MarketScanData
    macro: MacroIndicators
    issue: dict[str, Any]
    additional_news: list[NewsArticle]
    screened: list[CandidateScreenData]


# ── 스텝 함수 ──


async def collect_market_data(ctx: IssueDiveContext) -> None:
    """Stage 1: 시장 스캔 + 매크로 지표를 병렬 수집한다."""
    logger.info("[이슈딥다이브 Stage 1] 시장 스캔 + 매크로 지표 수집...")
    scan_data, macro_data = await asyncio.gather(scan_market(), fetch_macro_indicators())
    logger.info("[이슈딥다이브 Stage 1] 스캔 완료: 뉴스 %d건, 매크로 VIX=%s",
                len(scan_data.market_news), macro_data.vix)
    ctx["scan"] = scan_data
    ctx["macro"] = macro_data


async def dedup_issue_news(ctx: IssueDiveContext) -> None:
    """Stage 2: 별도 컬렉션으로 시맨틱 중복 제거."""
    from app.collector.dedup import dedup_news
    scan = ctx["scan"]
    scan.market_news = dedup_news(
        scan.market_news, lambda n: f"{n.headline} {n.summary}",
        "issue_dive_news", run_id=ctx["run_id"], pipeline="issue_dive",
    )
    if not scan.market_news:
        logger.info("새로운 뉴스 없음 — 이슈 딥다이브 스킵")
        ctx["skip"] = True


async def pick_issue(ctx: IssueDiveContext) -> None:
    """Stage 3: LLM #1에게 가장 중요한 이슈 1개를 선정한다."""
    logger.info("[이슈딥다이브 Stage 3] 이슈 선정 중...")
    issue = await to_thread(pick_top_issue, ctx["scan"], ctx["macro"], run_id=ctx["run_id"])
    logger.info("[이슈딥다이브 Stage 3] 선정 이슈: %s", issue.get("headline", ""))
    ctx["issue"] = issue


async def research_issue(ctx: IssueDiveContext) -> None:
    """Stage 4: 선정된 이슈의 키워드로 추가 뉴스 수집 + 관련 종목 스크리닝."""
    issue = ctx["issue"]
    keywords = issue.get("search_keywords", [])
    tickers = issue.get("related_tickers", [])

    # 키워드 기반 추가 뉴스 수집 (5 키워드 × 10건)
    logger.info("[이슈딥다이브 Stage 4] 추가 뉴스 수집: %d 키워드...", len(keywords))
    news_tasks = [fetch_news(query=kw, count=10) for kw in keywords[:5]]
    news_results = await asyncio.gather(*news_tasks)

    # 중복 링크 제거하여 합치기
    all_news: list[NewsArticle] = []
    seen_links: set[str] = set()
    for articles in news_results:
        for article in articles:
            if article.link not in seen_links:
                seen_links.add(article.link)
                all_news.append(article)

    logger.info("[이슈딥다이브 Stage 4] 추가 뉴스 %d건 수집", len(all_news))
    ctx["additional_news"] = all_news

    # 관련 종목 재무 스크리닝
    logger.info("[이슈딥다이브 Stage 4] %d개 종목 재무 스크리닝...", len(tickers))
    screened = await screen_candidates(tickers)
    logger.info("[이슈딥다이브 Stage 4] 스크리닝 완료: %d개 종목 데이터 확보", len(screened))
    ctx["screened"] = screened


async def generate_article(ctx: IssueDiveContext) -> None:
    """Stage 5: 수집한 심층 자료로 장문 피처 기사를 생성한다."""
    logger.info("[이슈딥다이브 Stage 5] 피처 기사 작성 중...")
    result = await to_thread(
        generate_issue_dive_article,
        ctx["issue"], ctx["additional_news"], ctx["screened"],
        ctx["scan"], ctx["macro"],
        run_id=ctx["run_id"],
    )
    ctx["result"] = result


ISSUE_DIVE_STEPS = [
    collect_market_data,
    dedup_issue_news,
    pick_issue,
    research_issue,
    generate_article,
    deliver,
]


async def run_issue_dive_pipeline(email_to: list[str] | None = []) -> str:
    """이슈 딥다이브 파이프라인 — 스텝 기반."""
    logger.info("이슈 딥다이브 파이프라인 시작: %s", date.today())
    ctx: IssueDiveContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "issue_dive",
        "briefing_type": BriefingType.ISSUE_DIVE,
    }
    await run_steps(ISSUE_DIVE_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
