"""경제 상식 파이프라인 — 토픽 큐에서 1건 선택 → 글 생성 → 발행.

하루 3회 (07:00 / 11:00 / 17:00) 실행.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from datetime import date

from app.core.models import BriefingType, EconomyTopic
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class EconomyContext(PipelineContext, total=False):
    topic: EconomyTopic
    topic_id: int
    pattern_type: str
    keyword: str
    faq_schema_json: str


async def pick_topic(ctx: EconomyContext) -> None:
    from app.seo.economy_queue import pick_next_economy_topic, seed_economy_topics

    topic = await pick_next_economy_topic()
    if not topic:
        logger.info("[Economy] 큐 비어있음 — 시드 삽입 시도")
        inserted = await seed_economy_topics()
        if inserted:
            topic = await pick_next_economy_topic()

    if not topic:
        logger.info("[Economy] 큐에 pending 토픽 없음 — 스킵")
        ctx["skip"] = True
        return

    ctx["topic"] = topic
    ctx["topic_id"] = topic.id
    ctx["pattern_type"] = topic.pattern_type
    ctx["keyword"] = topic.keyword
    logger.info("[Economy Stage 1] 토픽 선택: id=%d, keyword=%s", topic.id, topic.keyword)


async def dedup_check(ctx: EconomyContext) -> None:
    from app.seo.wp_dedup import check_content_duplicate
    from app.seo.economy_queue import mark_economy_skipped

    topic = ctx["topic"]
    is_dup = await to_thread(check_content_duplicate, topic.title_template, topic.keyword)

    if is_dup:
        logger.info("[Economy Stage 2] 중복 감지 — 스킵: %s", topic.title_template)
        await mark_economy_skipped(ctx["topic_id"])
        ctx["skip"] = True
        return

    logger.info("[Economy Stage 2] 중복 아님 — 진행: %s", topic.title_template)


async def generate_article(ctx: EconomyContext) -> None:
    from app.prompts.economy_content import generate_economy_article

    logger.info("[Economy Stage 3] AI 글 생성: %s", ctx["keyword"])
    result = await to_thread(
        generate_economy_article,
        ctx["pattern_type"],
        ctx["keyword"],
        ctx["run_id"],
    )
    ctx["result"] = result
    logger.info("[Economy Stage 3] 글 생성 완료: '%s'", result.title[:50])


async def inject_faq_schema(ctx: EconomyContext) -> None:
    from app.seo.faq_schema import extract_faq_schema_json

    result: BriefingResult = ctx["result"]
    faq_json = extract_faq_schema_json(result.html)
    if faq_json:
        ctx["faq_schema_json"] = faq_json


async def post_publish_hooks(ctx: EconomyContext) -> None:
    from app.seo.wp_dedup import register_published_content
    from app.seo.economy_queue import mark_economy_published

    result: BriefingResult = ctx["result"]

    from app.core.database import async_session
    from app.core.models import Briefing
    from sqlalchemy import select

    async with async_session() as db:
        row = await db.execute(
            select(Briefing)
            .where(
                Briefing.date == date.today(),
                Briefing.briefing_type == BriefingType.ECONOMY_CONTENT,
                Briefing.title == result.title,
            )
            .order_by(Briefing.created_at.desc())
            .limit(1)
        )
        briefing = row.scalar_one_or_none()

    if not briefing:
        logger.warning("[Economy Stage 5] DB에서 발행된 브리핑을 찾지 못함")
        return

    briefing_id = briefing.id
    blog_url = briefing.blog_url or ""

    wp_post_id = 0
    if blog_url:
        try:
            import httpx, base64
            from app.core.config import get_settings
            settings = get_settings()
            credentials = f"{settings.wp_user}:{settings.wp_app_password}"
            token = base64.b64encode(credentials.encode()).decode()
            async with httpx.AsyncClient(timeout=10, headers={"Authorization": f"Basic {token}"}) as client:
                resp = await client.get(
                    f"{settings.wp_url}/wp-json/wp/v2/posts",
                    params={"slug": result.slug, "per_page": 1},
                )
                if resp.status_code == 200 and resp.json():
                    wp_post_id = resp.json()[0]["id"]
        except Exception as e:
            logger.warning("WP post_id 조회 실패: %s", e)

    await to_thread(register_published_content, result.title, result.focus_keyword)
    await mark_economy_published(ctx["topic_id"], briefing_id, wp_post_id)
    logger.info("[Economy Stage 5] 후처리 완료: briefing_id=%d", briefing_id)


ECONOMY_STEPS = [
    pick_topic,
    dedup_check,
    generate_article,
    inject_faq_schema,
    deliver,
    post_publish_hooks,
]


async def run_economy_content_pipeline(email_to: list[str] | None = []) -> str:
    logger.info("경제 상식 파이프라인 시작: %s", date.today())

    ctx: EconomyContext = {
        "run_id": generate_run_id(),
        "email_to": [],  # 이메일 발송 없음
        "pipeline": "economy_content",
        "briefing_type": BriefingType.ECONOMY_CONTENT,
    }

    await run_steps(ECONOMY_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
