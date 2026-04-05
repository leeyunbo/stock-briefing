"""나스닥 브리핑 파이프라인.

collect → summarize → deliver
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from dataclasses import dataclass, field
from datetime import date

from app.collector.nasdaq import NasdaqSummary, fetch_nasdaq_summary
from app.collector.snapshot import save_nasdaq_snapshot, fetch_index_history
from app.core.models import IndexSnapshot
from app.core.models import BriefingType
from app.pipeline.base import PipelineContext, deliver, run_steps
from app.pipeline.review import review_content
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


# ── 수집 데이터 ──


@dataclass
class NasdaqCollectedData:
    """나스닥 수집 단계 결과물."""

    summary: NasdaqSummary
    index_history: list[IndexSnapshot] = field(default_factory=list)


class NasdaqContext(PipelineContext, total=False):
    """NASDAQ 파이프라인 컨텍스트."""

    collected: NasdaqCollectedData


# ── 스텝 함수 ──


async def collect_nasdaq_data(ctx: NasdaqContext) -> None:
    """나스닥 데이터를 수집한다."""
    try:
        summary = await fetch_nasdaq_summary()
    except Exception as e:
        logger.error("나스닥 데이터 수집 실패: %s", e)
        summary = NasdaqSummary()

    try:
        await save_nasdaq_snapshot(summary)
    except Exception as e:
        logger.warning("나스닥 스냅샷 저장 실패 (무시): %s", e)

    index_history: list[IndexSnapshot] = []
    try:
        index_history = await fetch_index_history(["nasdaq", "sp500", "dow"])
    except Exception as e:
        logger.warning("나스닥 과거 추이 조회 실패 (무시): %s", e)

    logger.info(
        "나스닥 수집 완료: 지수 %d개, 종목 %d개, 과거 추이 %d건",
        len(summary.indices), len(summary.stocks), len(index_history),
    )
    ctx["collected"] = NasdaqCollectedData(summary=summary, index_history=index_history)


async def summarize_nasdaq(ctx: NasdaqContext) -> None:
    """수집 데이터를 AI로 요약한다."""
    from app.prompts.nasdaq import summarize_nasdaq_data
    ctx["result"] = await to_thread(summarize_nasdaq_data, ctx["collected"], run_id=ctx.get("run_id", ""))


NASDAQ_STEPS = [
    collect_nasdaq_data,
    summarize_nasdaq,
    review_content,
    deliver,
]


# ── 오케스트레이터 ──


async def run_nasdaq_pipeline(email_to: list[str] | None = []) -> str:
    """전체 나스닥 파이프라인: 수집 → 요약 → 저장 → 발송 — 스텝 기반.

    Args:
        email_to: 발송 대상. None=전체 구독자, []=발송 안 함, ["a@b.com"]=특정 주소.
    """
    logger.info("나스닥 브리핑 파이프라인 시작: %s", date.today())
    ctx: NasdaqContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "nasdaq",
        "briefing_type": BriefingType.NASDAQ,
    }
    await run_steps(NASDAQ_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
