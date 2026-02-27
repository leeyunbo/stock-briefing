"""파이프라인 공통 — 결과 데이터 클래스, DB 저장, 이메일 발송."""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.core.database import async_session
from app.core.models import Briefing, Subscriber
from app.publishing.email_sender import send_briefing_to_subscribers
from app.publishing.email_template import render_email

logger = logging.getLogger(__name__)


@dataclass
class BriefingResult:
    """요약 단계의 결과물."""

    title: str
    html: str
    slug: str = ""
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)


async def save_briefing(result: BriefingResult, briefing_type: str = "kr") -> None:
    """브리핑을 DB에 저장한다 (같은 날+같은 타입 재실행 시 업데이트)."""
    today = date.today()
    async with async_session() as db:
        existing = await db.execute(
            select(Briefing).where(Briefing.date == today, Briefing.briefing_type == briefing_type)
        )
        briefing = existing.scalar_one_or_none()
        if briefing:
            briefing.title = result.title
            briefing.content_html = result.html
        else:
            db.add(Briefing(date=today, briefing_type=briefing_type, title=result.title, content_html=result.html))
        await db.commit()


async def send_emails(result: BriefingResult) -> None:
    """구독자에게 이메일을 발송한다."""
    async with async_session() as db:
        rows = await db.execute(select(Subscriber.email).where(Subscriber.is_active.is_(True)))
        emails = [row[0] for row in rows.all()]

    if not emails:
        logger.info("구독자 없음 — 발송 건너뜀")
        return

    email_html = render_email(result.title, result.html)
    results = await send_briefing_to_subscribers(emails, result.title, email_html)
    logger.info("발송 완료: 성공 %d, 실패 %d", results["success"], results["fail"])
