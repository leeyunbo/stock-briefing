"""파이프라인 공통 — 스텝 러너, 결과 데이터 클래스, Publisher 패턴."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, TypedDict

from sqlalchemy import select

from app.core.database import async_session
from app.core.models import Briefing, BriefingType, Subscriber
from app.publishing.email_sender import send_briefing_to_subscribers
from app.publishing.email_template import render_email
from app.publishing.og_image import CATEGORY_DISPLAY, generate_og_image
from app.publishing.wordpress import publish_to_wordpress

logger = logging.getLogger(__name__)


# ── 결과 데이터 ──


@dataclass
class BriefingResult:
    """요약 단계의 결과물."""

    title: str
    html: str
    slug: str = ""
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)
    focus_keyword: str = ""
    image_keyword: str = ""


# ── 파이프라인 컨텍스트 타입 ──


class PipelineContext(TypedDict, total=False):
    """모든 파이프라인이 공유하는 기본 컨텍스트."""

    run_id: str
    email_to: list[str] | None
    pipeline: str
    briefing_type: str
    result: BriefingResult
    skip: bool


# ── 스텝 러너 ──


async def run_steps(steps: list, ctx: PipelineContext) -> PipelineContext:
    """스텝 리스트를 순서대로 실행한다. ctx["skip"]=True 시 중단."""
    for step in steps:
        await step(ctx)
        if ctx.get("skip"):
            break
    return ctx


# ── Publisher 프로토콜 + 구현체 ──


class Publisher(Protocol):
    async def publish(self, result: BriefingResult, briefing_type: str, **kwargs) -> dict:
        ...


class DBPublisher:
    # 하루에 여러 건 발행 가능한 타입 (upsert 대신 항상 INSERT)
    _MULTI_PER_DAY = {BriefingType.ISSUE_DIVE}

    async def publish(self, result: BriefingResult, briefing_type: str, **kwargs) -> dict:
        today = date.today()
        async with async_session() as db:
            if briefing_type in self._MULTI_PER_DAY:
                briefing = Briefing(
                    date=today, briefing_type=briefing_type,
                    title=result.title, content_html=result.html,
                    excerpt=result.excerpt or "",
                )
                db.add(briefing)
            else:
                existing = await db.execute(
                    select(Briefing).where(Briefing.date == today, Briefing.briefing_type == briefing_type)
                )
                briefing = existing.scalar_one_or_none()
                if briefing:
                    briefing.title = result.title
                    briefing.content_html = result.html
                    briefing.excerpt = result.excerpt or ""
                else:
                    briefing = Briefing(
                        date=today, briefing_type=briefing_type,
                        title=result.title, content_html=result.html,
                        excerpt=result.excerpt or "",
                    )
                    db.add(briefing)
            await db.flush()
            briefing_id = briefing.id
            await db.commit()
        return {"briefing_id": briefing_id}

    @staticmethod
    async def update_blog_url(briefing_id: int, blog_url: str) -> None:
        """WordPress 발행 후 blog_url을 DB에 업데이트한다."""
        async with async_session() as db:
            existing = await db.execute(
                select(Briefing).where(Briefing.id == briefing_id)
            )
            briefing = existing.scalar_one_or_none()
            if briefing:
                briefing.blog_url = blog_url
                await db.commit()


class WordPressPublisher:
    async def publish(self, result: BriefingResult, briefing_type: str, **kwargs) -> dict:
        from app.publishing.unsplash import fetch_unsplash_image

        category = CATEGORY_DISPLAY.get(briefing_type, briefing_type)
        og_image = generate_og_image(result.title, category)

        # Unsplash 이미지 검색
        unsplash_result = None
        if result.image_keyword:
            unsplash_result = await fetch_unsplash_image(result.image_keyword)

        wp_result = await publish_to_wordpress(
            result.title, result.html, briefing_type,
            slug=result.slug, excerpt=result.excerpt, tags=result.tags,
            og_image=og_image,
            focus_keyword=result.focus_keyword,
            seo_description=result.excerpt,
            unsplash_image=unsplash_result,
        )
        blog_url = wp_result[1] if wp_result else ""
        briefing_id = kwargs.get("briefing_id")
        if blog_url and briefing_id:
            await DBPublisher.update_blog_url(briefing_id, blog_url)
        return {"blog_url": blog_url, "category": category}


class EmailPublisher:
    async def publish(self, result: BriefingResult, briefing_type: str, **kwargs) -> dict:
        blog_url = kwargs.get("blog_url", "")
        category = kwargs.get("category", "")
        email_to: list[str] | None = kwargs.get("email_to")

        if email_to is not None:
            if not email_to:
                return {}
            emails = email_to
        else:
            async with async_session() as db:
                rows = await db.execute(select(Subscriber.email).where(Subscriber.is_active.is_(True)))
                emails = [row[0] for row in rows.all()]

        if not emails:
            logger.info("구독자 없음 — 발송 건너뜀")
            return {}

        excerpt = result.excerpt or "AI가 정리한 오늘의 시장 브리핑이 도착했어요."
        email_html = render_email(result.title, excerpt, blog_url, category)
        send_result = await send_briefing_to_subscribers(emails, result.title, email_html)
        logger.info("이메일 발송: 성공 %d, 실패 %d", send_result["success"], send_result["fail"])
        return send_result


DEFAULT_PUBLISHERS: list[Publisher] = [DBPublisher(), WordPressPublisher(), EmailPublisher()]


# ── 공통 deliver 스텝 ──


async def deliver(ctx: PipelineContext) -> None:
    """Publisher 리스트를 순회하며 발행한다."""
    result: BriefingResult = ctx["result"]
    briefing_type: str = ctx["briefing_type"]
    email_to: list[str] | None = ctx.get("email_to")

    shared: dict = {"email_to": email_to}
    for pub in DEFAULT_PUBLISHERS:
        out = await pub.publish(result, briefing_type, **shared)
        shared.update(out)


# ── 하위호환 유틸 ──


async def save_briefing(result: BriefingResult, briefing_type: str = "kr") -> None:
    """브리핑을 DB에 저장한다 (같은 날+같은 타입 재실행 시 업데이트)."""
    await DBPublisher().publish(result, briefing_type)
