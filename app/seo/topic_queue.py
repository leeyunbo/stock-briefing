"""SEO 토픽 큐 관리 — 종목×패턴 시드 + 우선순위 기반 선택."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import async_session
from app.core.models import SeoTopic

logger = logging.getLogger(__name__)

# ── 패턴 정의 ──

THEME_PATTERNS: dict[str, str] = {
    "theme_related": "{keyword} 관련주",
    "theme_leader": "{keyword} 대장주",
}

# ── 시드 데이터 ──

THEMES = [
    "AI 반도체", "2차전지", "로봇", "양자컴퓨터", "방산",
    "원전", "우주항공", "자율주행", "바이오", "리츠",
    "태양광", "풍력", "수소", "전고체배터리", "HBM",
]

CONCEPTS = [
    "PER", "PBR", "ROE", "배당수익률", "공매도",
    "ETF", "선물옵션", "IPO", "유상증자", "자사주매입",
    "CB 전환사채", "BW 신주인수권부사채", "스팩 SPAC", "리밸런싱", "분산투자",
]


def _build_seed_rows() -> list[dict]:
    """시드 토픽 목록 생성."""
    rows: list[dict] = []

    # 테마: 패턴별로 돌림
    for ptype, tmpl in THEME_PATTERNS.items():
        for theme in THEMES:
            rows.append({
                "pattern_type": ptype,
                "keyword": theme,
                "title_template": tmpl.format(keyword=theme),
                "focus_keyword": tmpl.format(keyword=theme),
                "priority": 8,
                "source": "template",
            })

    return rows


async def seed_topics() -> int:
    """시드 토픽을 DB에 삽입한다 (중복 무시).

    Returns:
        삽입된 행 수.
    """
    rows = _build_seed_rows()
    inserted = 0

    async with async_session() as db:
        for row in rows:
            stmt = sqlite_insert(SeoTopic).values(**row).on_conflict_do_nothing(
                index_elements=["pattern_type", "keyword"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("SEO 시드 토픽: %d건 삽입 (전체 %d건)", inserted, len(rows))
    return inserted


async def pick_next_topic() -> SeoTopic | None:
    """우선순위가 가장 높은 pending 토픽을 반환한다.

    정렬: priority DESC → id ASC (높은 우선순위 + 오래된 것 먼저).
    """
    async with async_session() as db:
        result = await db.execute(
            select(SeoTopic)
            .where(SeoTopic.status == "pending")
            .order_by(SeoTopic.priority.desc(), SeoTopic.id.asc())
            .limit(1)
        )
        topic = result.scalar_one_or_none()
        if topic:
            # detach from session
            db.expunge(topic)
        return topic


async def mark_published(topic_id: int, briefing_id: int, wp_post_id: int) -> None:
    """토픽을 published로 변경하고 발행 정보를 연결한다."""
    from datetime import UTC, datetime

    async with async_session() as db:
        result = await db.execute(
            select(SeoTopic).where(SeoTopic.id == topic_id)
        )
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "published"
            topic.briefing_id = briefing_id
            topic.wp_post_id = wp_post_id
            topic.published_at = datetime.now(UTC)
            await db.commit()
            logger.info("토픽 발행 완료: id=%d, keyword=%s", topic_id, topic.keyword)


async def mark_skipped(topic_id: int) -> None:
    """토픽을 skipped로 변경한다 (중복 등)."""
    async with async_session() as db:
        result = await db.execute(
            select(SeoTopic).where(SeoTopic.id == topic_id)
        )
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "skipped"
            await db.commit()
            logger.info("토픽 건너뜀: id=%d, keyword=%s", topic_id, topic.keyword)
