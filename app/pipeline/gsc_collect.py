"""GSC 수집 파이프라인 — 주 1회 Google Search Console 데이터 수집 + 기회 키워드 발굴."""

import logging

from app.collector.gsc import (
    create_gsc_topics,
    fetch_gsc_data,
    find_opportunity_keywords,
    save_gsc_data,
)

logger = logging.getLogger(__name__)


async def run_gsc_collection() -> str:
    """GSC 데이터 수집 → 기회 키워드 발굴 → 토픽 큐 추가.

    Returns:
        실행 결과 요약 문자열.
    """
    logger.info("GSC 수집 파이프라인 시작")

    # 1. GSC 데이터 수집 (최근 28일)
    data = await fetch_gsc_data(days=28)
    if not data:
        logger.info("GSC 데이터 없음 — 종료")
        return "GSC 데이터 없음"

    # 2. DB 저장
    saved = await save_gsc_data(data)
    logger.info("GSC 데이터 저장: %d건", saved)

    # 3. 기회 키워드 발굴
    opportunities = await find_opportunity_keywords()
    logger.info("기회 키워드: %d건", len(opportunities))

    # 4. 토픽 큐에 추가
    created = 0
    if opportunities:
        created = await create_gsc_topics(opportunities)
        logger.info("GSC 토픽 추가: %d건", created)

    summary = f"GSC 수집 완료: data={len(data)}, saved={saved}, opportunities={len(opportunities)}, topics={created}"
    logger.info(summary)
    return summary
