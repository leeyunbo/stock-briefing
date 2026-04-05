"""검수 파이프라인 스텝 — 기사 생성 후 deliver 전에 삽입."""

import logging
from asyncio import to_thread

from app.pipeline.base import BriefingResult, PipelineContext
from app.prompts.review import run_review

logger = logging.getLogger(__name__)


async def review_content(ctx: PipelineContext) -> None:
    """팩트체크 + 출처 확인 + 톤 검증 후 자동 교정."""
    result: BriefingResult = ctx["result"]
    logger.info("[검수 스텝] 검수 시작: %s", result.title)
    result.html = await to_thread(
        run_review,
        result.html,
        run_id=ctx.get("run_id", ""),
        pipeline=ctx.get("pipeline", ""),
    )
