"""SEO 토픽 큐 관리 — 종목×패턴 시드 + 우선순위 기반 선택."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import async_session
from app.core.models import SeoTopic

logger = logging.getLogger(__name__)

# ── 패턴 정의 ──

STOCK_PATTERNS: dict[str, str] = {
    "stock_dividend": "{keyword} 배당금 총정리",
    "stock_target_price": "{keyword} 목표주가 및 전망",
    "stock_earnings": "{keyword} 실적 분석",
    "stock_outlook": "{keyword} 주가 전망",
}

THEME_PATTERNS: dict[str, str] = {
    "theme_related": "{keyword} 관련주",
    "theme_leader": "{keyword} 대장주",
}

CONCEPT_PATTERNS: dict[str, str] = {
    "concept_definition": "{keyword}이란?",
    "concept_structure": "{keyword} 구조",
}

# ── 시드 데이터 ──

KR_STOCKS = [
    "삼성전자", "SK하이닉스", "현대차", "기아", "POSCO홀딩스",
    "셀트리온", "KB금융", "신한지주", "NAVER", "카카오",
    "LG에너지솔루션", "삼성바이오로직스", "현대모비스", "LG화학", "삼성SDI",
    "한화에어로스페이스", "HD현대중공업", "SK이노베이션", "두산에너빌리티", "크래프톤",
]

US_STOCKS: list[tuple[str, str]] = [
    ("엔비디아", "NVDA"), ("테슬라", "TSLA"), ("애플", "AAPL"),
    ("마이크로소프트", "MSFT"), ("아마존", "AMZN"), ("구글", "GOOGL"),
    ("메타", "META"), ("넷플릭스", "NFLX"), ("AMD", "AMD"), ("팔란티어", "PLTR"),
]

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

    # 종목: 패턴별로 종목을 돌려서 분산 (삼전→하이닉스→...→삼전 목표주가→...)
    all_stocks = [(stock, "") for stock in KR_STOCKS] + [(kw, tk) for kw, tk in US_STOCKS]

    for ptype, tmpl in STOCK_PATTERNS.items():
        for keyword, ticker in all_stocks:
            row = {
                "pattern_type": ptype,
                "keyword": keyword,
                "title_template": tmpl.format(keyword=keyword),
                "focus_keyword": tmpl.format(keyword=keyword).replace(" 총정리", ""),
                "priority": 10,
                "source": "template",
            }
            if ticker:
                row["ticker"] = ticker
            rows.append(row)

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

    # 개념: 패턴별로 돌림
    for ptype, tmpl in CONCEPT_PATTERNS.items():
        for concept in CONCEPTS:
            rows.append({
                "pattern_type": ptype,
                "keyword": concept,
                "title_template": tmpl.format(keyword=concept),
                "focus_keyword": tmpl.format(keyword=concept),
                "priority": 6,
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
