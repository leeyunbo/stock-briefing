"""스케줄러 — 스케줄링 설정만 담당. 비즈니스 로직은 각 파이프라인 모듈에."""

import logging

from app.pipeline.kospi import run_pipeline
from app.pipeline.nasdaq import run_nasdaq_pipeline
from app.pipeline.real_estate import run_real_estate_pipeline
from app.pipeline.research import run_news_dive_pipeline

logger = logging.getLogger(__name__)


def start_scheduler():
    """APScheduler로 브리핑을 스케줄링한다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # 한국 주식 브리핑: 화~토 오전 7시
    scheduler.add_job(
        run_pipeline,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="tue-sat",
        id="daily_briefing",
    )

    # 나스닥 마감 브리핑: 화~토 오전 8시 (나스닥 월~금 장마감 → 한국 다음날 아침)
    scheduler.add_job(
        run_nasdaq_pipeline,
        trigger="cron",
        hour=8,
        minute=0,
        day_of_week="tue-sat",
        id="nasdaq_briefing",
    )

    # 뉴스 딥다이브: 화~토 오전 9시 (나스닥 브리핑 후 시장 코멘터리)
    scheduler.add_job(
        run_news_dive_pipeline,
        trigger="cron",
        hour=9,
        minute=0,
        day_of_week="tue-sat",
        id="news_dive",
    )

    # 부동산 브리핑: 월~토 오전 7시 (일요일 제외, 이메일 발송 없음)
    scheduler.add_job(
        run_real_estate_pipeline,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="mon-sat",
        id="real_estate_briefing",
        kwargs={"email_to": []},
    )

    scheduler.start()
    logger.info("스케줄러 시작: 한국 화~토 7시, 나스닥 화~토 8시, 뉴스딥다이브 화~토 9시, 부동산 월~토 7시")
    return scheduler
