"""스케줄러 — 스케줄링 설정만 담당. 비즈니스 로직은 pipeline.py에."""

import logging

from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def start_scheduler():
    """APScheduler로 매일 아침 7시 브리핑을 스케줄링한다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_pipeline,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="mon-sat",
        id="daily_briefing",
    )
    scheduler.start()
    logger.info("스케줄러 시작: 월~토 매일 아침 7시 브리핑 발송")
    return scheduler
