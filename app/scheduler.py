"""스케줄러 — 스케줄링 설정만 담당. 비즈니스 로직은 pipeline.py / nasdaq_pipeline.py에."""

import logging

from app.nasdaq_pipeline import run_nasdaq_pipeline
from app.pipeline import run_pipeline

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

    # 나스닥 마감 브리핑: 월~금 오전 8시 (나스닥 장마감 직후)
    scheduler.add_job(
        run_nasdaq_pipeline,
        trigger="cron",
        hour=8,
        minute=0,
        day_of_week="mon-fri",
        id="nasdaq_briefing",
    )

    scheduler.start()
    logger.info("스케줄러 시작: 한국 화~토 7시, 나스닥 월~금 8시")
    return scheduler
