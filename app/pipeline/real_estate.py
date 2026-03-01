"""부동산 브리핑 파이프라인.

collect → dedup → report → deliver
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.real_estate import (
    RealEstateData,
    fetch_all_subscription_data,
    fetch_real_estate_news,
)
from app.core.models import BriefingType
from app.pipeline.base import PipelineContext, deliver, run_steps
from app.prompts.real_estate import generate_real_estate_report
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class RealEstateContext(PipelineContext, total=False):
    """부동산 파이프라인 컨텍스트."""

    news: list[Any]
    subscriptions: list[Any]
    prices: dict[str, Any]


# ── 스텝 함수 ──


async def collect_real_estate_data(ctx: RealEstateContext) -> None:
    """뉴스 + 청약 데이터를 병렬 수집한다."""
    logger.info("[Stage 1] 부동산 뉴스 + 청약 데이터 수집...")
    news_result, (subscriptions, prices) = await asyncio.gather(
        fetch_real_estate_news(),
        fetch_all_subscription_data(),
    )
    logger.info(
        "[Stage 1] 수집 완료: 뉴스 %d건, 청약 %d건, 분양가 %d건",
        len(news_result), len(subscriptions), len(prices),
    )
    ctx["news"] = news_result
    ctx["subscriptions"] = subscriptions
    ctx["prices"] = prices


async def dedup_real_estate_news(ctx: RealEstateContext) -> None:
    """시맨틱 중복 제거 + trace."""
    from app.collector.dedup import dedup_news
    ctx["news"] = dedup_news(
        ctx["news"], lambda n: f"{n.title} {n.summary}",
        "real_estate_news", threshold=0.85,
        run_id=ctx["run_id"], pipeline="real_estate",
    )
    if not ctx["news"] and not ctx["subscriptions"]:
        logger.info("새로운 뉴스/청약 없음 — 파이프라인 스킵")
        ctx["skip"] = True


async def generate_re_report(ctx: RealEstateContext) -> None:
    """Claude에게 부동산 브리핑 리포트를 생성시킨다."""
    data = RealEstateData(
        news=ctx["news"],
        subscriptions=ctx["subscriptions"],
        prices=ctx["prices"],
        scan_date=date.today().isoformat(),
    )
    logger.info("[Stage 2] 부동산 브리핑 리포트 작성 중...")
    ctx["result"] = await to_thread(generate_real_estate_report, data, run_id=ctx.get("run_id", ""))


REAL_ESTATE_STEPS = [
    collect_real_estate_data,
    dedup_real_estate_news,
    generate_re_report,
    deliver,
]


# ── 오케스트레이터 ──


async def run_real_estate_pipeline(email_to: list[str] | None = None) -> str:
    """부동산 브리핑 파이프라인 — 스텝 기반."""
    logger.info("부동산 브리핑 파이프라인 시작: %s", date.today())
    ctx: RealEstateContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "real_estate",
        "briefing_type": BriefingType.REAL_ESTATE,
    }
    await run_steps(REAL_ESTATE_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
