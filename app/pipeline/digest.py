"""데일리 다이제스트 — 오늘 발행된 글 목록을 1통으로 발송."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select

from app.core.database import async_session
from app.core.models import Briefing, Subscriber
from app.publishing.email_sender import send_briefing_to_subscribers
from app.publishing.og_image import CATEGORY_DISPLAY

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=False)

# 카테고리별 뱃지 색상 (이메일 템플릿용)
_BADGE_COLORS: dict[str, str] = {
    "국내주식": "#e74c3c",
    "미국주식": "#3498db",
    "부동산": "#27ae60",
    "오늘의 뉴스": "#9b59b6",
    "이슈 딥다이브": "#e67e22",
}


async def run_daily_digest() -> None:
    """오늘 발행된 브리핑을 조회하여 다이제스트 이메일 1통을 발송한다."""
    today = date.today()
    logger.info("데일리 다이제스트 시작: %s", today)

    # 오늘 발행된 브리핑 조회
    async with async_session() as db:
        result = await db.execute(
            select(Briefing)
            .where(Briefing.date == today)
            .order_by(Briefing.created_at)
        )
        briefings = result.scalars().all()

    if not briefings:
        logger.info("오늘 발행된 브리핑 없음 — 다이제스트 스킵")
        return

    # 템플릿 데이터 구성
    items = []
    for b in briefings:
        category = CATEGORY_DISPLAY.get(b.briefing_type, b.briefing_type)
        items.append({
            "category": category,
            "badge_color": _BADGE_COLORS.get(category, "#3498db"),
            "title": b.title,
            "excerpt": b.excerpt or "",
            "blog_url": b.blog_url or "",
        })

    date_display = today.strftime("%Y년 %m월 %d일")
    template = _env.get_template("email_digest.html")
    email_html = template.render(date_display=date_display, items=items)

    # 구독자 조회
    async with async_session() as db:
        rows = await db.execute(
            select(Subscriber.email).where(Subscriber.is_active.is_(True))
        )
        emails = [row[0] for row in rows.all()]

    if not emails:
        logger.info("구독자 없음 — 다이제스트 발송 건너뜀")
        return

    subject = f"오늘의 머니다이브 — {date_display}"
    send_result = await send_briefing_to_subscribers(emails, subject, email_html)
    logger.info(
        "다이제스트 발송 완료: %d건 브리핑, 성공 %d, 실패 %d",
        len(items), send_result["success"], send_result["fail"],
    )
