"""SEO 콘텐츠 파이프라인 — 토픽 큐에서 1건 선택 → 글 생성 → 발행.

매일 14:00에 실행되어 하루 1개 SEO 글을 발행한다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.kr_research_models import KRStockResearchData
from app.collector.research_models import StockResearchData
from app.core.models import BriefingType, SeoTopic
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class SeoContentContext(PipelineContext, total=False):
    """SEO 콘텐츠 파이프라인 컨텍스트."""

    topic: SeoTopic
    topic_id: int
    pattern_type: str
    keyword: str
    kr_data: KRStockResearchData | None
    us_data: StockResearchData | None
    wp_post_id: int
    blog_url: str


# ── 스텝 함수 ──


async def pick_topic(ctx: SeoContentContext) -> None:
    """Stage 1: 토픽 큐에서 다음 토픽을 선택한다."""
    from app.seo.topic_queue import pick_next_topic, seed_topics

    topic = await pick_next_topic()
    if not topic:
        # 시드 자동 삽입 후 재시도
        logger.info("[SEO] 큐 비어있음 — 시드 삽입 시도")
        inserted = await seed_topics()
        if inserted:
            topic = await pick_next_topic()

    if not topic:
        logger.info("[SEO] 큐에 pending 토픽 없음 — 스킵")
        ctx["skip"] = True
        return

    ctx["topic"] = topic
    ctx["topic_id"] = topic.id
    ctx["pattern_type"] = topic.pattern_type
    ctx["keyword"] = topic.keyword
    logger.info(
        "[SEO Stage 1] 토픽 선택: id=%d, pattern=%s, keyword=%s",
        topic.id, topic.pattern_type, topic.keyword,
    )


async def classify_and_collect(ctx: SeoContentContext) -> None:
    """Stage 2: 패턴에 따라 데이터를 수집한다.

    stock_* 패턴이면 ticker 유무로 US/KR을 구분하여 풍부한 수집기를 호출한다.
    theme_*/concept_* 패턴이면 데이터 수집 없이 진행한다.
    """
    pattern = ctx["pattern_type"]
    keyword = ctx["keyword"]

    if pattern.startswith("stock_"):
        topic: SeoTopic = ctx["topic"]
        ticker = topic.ticker

        if ticker:  # US 종목
            logger.info("[SEO Stage 2] US 종목 데이터 수집: %s (%s)", keyword, ticker)
            from app.collector.stock_research import fetch_stock_research
            ctx["us_data"] = await fetch_stock_research(ticker)
        else:  # KR 종목
            logger.info("[SEO Stage 2] KR 종목 데이터 수집: %s", keyword)
            from app.collector.kr_stock_research import fetch_kr_stock_research
            ctx["kr_data"] = await fetch_kr_stock_research(keyword)
    else:
        logger.info("[SEO Stage 2] 데이터 수집 불필요: pattern=%s", pattern)


async def dedup_check(ctx: SeoContentContext) -> None:
    """Stage 3: ChromaDB로 기존 콘텐츠와 중복 검사."""
    from app.seo.wp_dedup import check_content_duplicate
    from app.seo.topic_queue import mark_skipped

    topic = ctx["topic"]
    is_dup = await to_thread(check_content_duplicate, topic.title_template, topic.keyword)

    if is_dup:
        logger.info("[SEO Stage 3] 중복 감지 — 토픽 스킵: %s", topic.title_template)
        await mark_skipped(ctx["topic_id"])
        ctx["skip"] = True
        return

    logger.info("[SEO Stage 3] 중복 아님 — 진행: %s", topic.title_template)


async def generate_article(ctx: SeoContentContext) -> None:
    """Stage 4: AI로 SEO 글을 생성한다."""
    from app.prompts.seo_content import generate_seo_article

    logger.info("[SEO Stage 4] AI 글 생성: %s", ctx["keyword"])
    result = await to_thread(
        generate_seo_article,
        ctx["pattern_type"],
        ctx["keyword"],
        ctx.get("kr_data"),
        ctx.get("us_data"),
        ctx["run_id"],
    )
    ctx["result"] = result
    logger.info("[SEO Stage 4] 글 생성 완료: '%s'", result.title[:50])


async def post_publish_hooks(ctx: SeoContentContext) -> None:
    """Stage 6: 발행 후 처리 — dedup 등록 + 토픽 상태 갱신 + 내부 링크."""
    from app.seo.wp_dedup import register_published_content
    from app.seo.topic_queue import mark_published
    from app.seo.internal_links import process_internal_links_for_new_post, assign_to_cluster

    result: BriefingResult = ctx["result"]

    # WP 발행 결과에서 post_id와 blog_url 가져오기
    # deliver 스텝에서 shared에 저장된 정보를 직접 가져올 수 없으므로
    # DB에서 최신 briefing을 조회
    from app.core.database import async_session
    from app.core.models import Briefing
    from sqlalchemy import select

    async with async_session() as db:
        row = await db.execute(
            select(Briefing)
            .where(
                Briefing.date == date.today(),
                Briefing.briefing_type == BriefingType.SEO_CONTENT,
                Briefing.title == result.title,
            )
            .order_by(Briefing.created_at.desc())
            .limit(1)
        )
        briefing = row.scalar_one_or_none()

    if not briefing:
        logger.warning("[SEO Stage 6] DB에서 발행된 브리핑을 찾지 못함")
        return

    briefing_id = briefing.id
    blog_url = briefing.blog_url or ""

    # WP post_id 추출 (blog_url이 있으면 WP에서 발행된 것)
    wp_post_id = 0
    if blog_url:
        # WordPress에서 post_id 조회
        try:
            import httpx
            import base64
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

    # 1. dedup DB 등록
    await to_thread(register_published_content, result.title, result.focus_keyword)

    # 2. 토픽 상태 갱신
    await mark_published(ctx["topic_id"], briefing_id, wp_post_id)

    # 3. 내부 링크 처리
    if wp_post_id and blog_url:
        try:
            link_count = await process_internal_links_for_new_post(
                wp_post_id, blog_url, result.title, result.focus_keyword,
            )
            logger.info("[SEO Stage 6] 내부 링크 %d건 처리", link_count)
        except Exception as e:
            logger.warning("내부 링크 처리 실패: %s", e)

        # 4. 클러스터 배정
        try:
            await assign_to_cluster(wp_post_id, blog_url, result.title, result.focus_keyword)
        except Exception as e:
            logger.warning("클러스터 배정 실패: %s", e)

    logger.info("[SEO Stage 6] 후처리 완료: briefing_id=%d", briefing_id)


SEO_CONTENT_STEPS = [
    pick_topic,
    classify_and_collect,
    dedup_check,
    generate_article,
    deliver,
    post_publish_hooks,
]


async def run_seo_content_pipeline(email_to: list[str] | None = []) -> str:
    """SEO 콘텐츠 파이프라인 실행.

    Returns:
        생성된 HTML (또는 빈 문자열).
    """
    logger.info("SEO 콘텐츠 파이프라인 시작: %s", date.today())

    ctx: SeoContentContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "seo_content",
        "briefing_type": BriefingType.SEO_CONTENT,
    }

    await run_steps(SEO_CONTENT_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
