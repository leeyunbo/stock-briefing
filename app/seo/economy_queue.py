"""경제 상식 토픽 큐 — 부동산/경제/투자 개념 시드 + 우선순위 기반 선택."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import async_session
from app.core.models import EconomyTopic

logger = logging.getLogger(__name__)

# ── 패턴 정의 ──

PATTERNS: dict[str, str] = {
    "economy_realestate": "{keyword} 뜻과 핵심 정리",
    "economy_concept": "{keyword} 쉽게 이해하기",
    "economy_invest": "{keyword} 완벽 정리",
}

# ── 시드 데이터 ──

REALESTATE_KEYWORDS = [
    "청약", "전세", "월세", "갭투자", "LTV",
    "DTI", "DSR", "재개발", "재건축", "분양가상한제",
    "전세사기", "역전세", "공시지가", "취득세", "양도소득세",
    "보유세", "종합부동산세", "임대차3법", "깡통전세", "전세보증보험",
    "주택담보대출", "역모기지론", "부동산 PF", "미분양", "입주권",
]

ECONOMY_KEYWORDS = [
    "인플레이션", "디플레이션", "스태그플레이션", "기준금리", "환율",
    "GDP", "CPI", "PPI", "무역수지", "경상수지",
    "양적완화", "테이퍼링", "긴축재정", "재정정책", "통화정책",
    "경기침체", "경기과열", "빅스텝", "자이언트스텝", "피벗",
    "달러 강세", "엔 캐리 트레이드", "글로벌 공급망", "리쇼어링", "프렌드쇼어링",
]

INVEST_KEYWORDS = [
    "PER", "PBR", "ROE", "배당수익률", "공매도",
    "ETF", "선물옵션", "IPO", "유상증자", "자사주매입",
    "CB 전환사채", "BW 신주인수권부사채", "스팩 SPAC", "리밸런싱", "분산투자",
    "가치투자", "성장주 투자", "배당주 투자", "인덱스 펀드", "적립식 투자",
    "포트폴리오 구성", "자산배분", "헤지펀드", "사모펀드", "TDF 펀드",
]


def _build_seed_rows() -> list[dict]:
    rows: list[dict] = []

    for keyword in REALESTATE_KEYWORDS:
        rows.append({
            "pattern_type": "economy_realestate",
            "keyword": keyword,
            "title_template": PATTERNS["economy_realestate"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 10,
            "source": "template",
        })

    for keyword in ECONOMY_KEYWORDS:
        rows.append({
            "pattern_type": "economy_concept",
            "keyword": keyword,
            "title_template": PATTERNS["economy_concept"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 10,
            "source": "template",
        })

    for keyword in INVEST_KEYWORDS:
        rows.append({
            "pattern_type": "economy_invest",
            "keyword": keyword,
            "title_template": PATTERNS["economy_invest"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 8,
            "source": "template",
        })

    return rows


async def seed_economy_topics() -> int:
    rows = _build_seed_rows()
    inserted = 0

    async with async_session() as db:
        for row in rows:
            stmt = sqlite_insert(EconomyTopic).values(**row).on_conflict_do_nothing(
                index_elements=["pattern_type", "keyword"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("경제 상식 시드 토픽: %d건 삽입 (전체 %d건)", inserted, len(rows))
    return inserted


async def pick_next_economy_topic() -> EconomyTopic | None:
    async with async_session() as db:
        result = await db.execute(
            select(EconomyTopic)
            .where(EconomyTopic.status == "pending")
            .order_by(EconomyTopic.priority.desc(), EconomyTopic.id.asc())
            .limit(1)
        )
        topic = result.scalar_one_or_none()
        if topic:
            db.expunge(topic)
        return topic


async def mark_economy_published(topic_id: int, briefing_id: int, wp_post_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(EconomyTopic).where(EconomyTopic.id == topic_id))
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "published"
            topic.briefing_id = briefing_id
            topic.wp_post_id = wp_post_id
            topic.published_at = datetime.now(UTC)
            await db.commit()
            logger.info("경제 상식 토픽 발행: id=%d, keyword=%s", topic_id, topic.keyword)


async def mark_economy_skipped(topic_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(EconomyTopic).where(EconomyTopic.id == topic_id))
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "skipped"
            await db.commit()
