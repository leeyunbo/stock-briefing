"""스케줄러 — 스케줄링 설정만 담당. 비즈니스 로직은 각 파이프라인 모듈에."""

import logging

from app.pipeline.kospi import run_pipeline
from app.pipeline.nasdaq import run_nasdaq_pipeline
from app.pipeline.real_estate import run_real_estate_pipeline
from app.pipeline.research import run_news_dive_pipeline
from app.pipeline.issue_dive import run_issue_dive_pipeline
from app.pipeline.digest import run_daily_digest
from app.pipeline.stock_deep_dive import run_stock_deep_dive_pipeline

logger = logging.getLogger(__name__)


def start_scheduler():
    """APScheduler로 브리핑을 스케줄링한다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(
        timezone="Asia/Seoul",
        job_defaults={"misfire_grace_time": 300},
    )

    # 한국 주식 브리핑: 월~금 오후 8시 (당일 장마감 후)
    scheduler.add_job(
        run_pipeline,
        trigger="cron",
        hour=20,
        minute=0,
        day_of_week="mon-fri",
        id="daily_briefing",
        kwargs={"email_to": []},
    )

    # 나스닥 마감 브리핑: 화~토 오전 8시 (나스닥 월~금 장마감 → 한국 다음날 아침)
    scheduler.add_job(
        run_nasdaq_pipeline,
        trigger="cron",
        hour=8,
        minute=0,
        day_of_week="tue-sat",
        id="nasdaq_briefing",
        kwargs={"email_to": []},
    )

    # 뉴스 딥다이브: 매일 오전 9시 (뉴스는 주말에도 발생)
    scheduler.add_job(
        run_news_dive_pipeline,
        trigger="cron",
        hour=9,
        minute=0,
        id="news_dive",
        kwargs={"email_to": []},
    )

    # 이슈 딥다이브: 매일 3회 (10시, 15시, 21시)
    scheduler.add_job(
        run_issue_dive_pipeline,
        trigger="cron",
        hour="10,15,21",
        minute=0,
        id="issue_dive",
        kwargs={"email_to": []},
    )

    # 부동산 브리핑: 월요일 오전 7시
    scheduler.add_job(
        run_real_estate_pipeline,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="mon",
        id="real_estate_briefing",
        kwargs={"email_to": []},
    )

    # 종목 딥다이브 (자동 모드): 매일 11시
    scheduler.add_job(
        run_stock_deep_dive_pipeline,
        trigger="cron",
        hour=11,
        minute=0,
        id="stock_deep_dive",
        kwargs={"email_to": []},
    )

    # 데일리 다이제스트: 매일 밤 22시 — 오늘 발행된 글 목록 1통
    scheduler.add_job(
        run_daily_digest,
        trigger="cron",
        hour=22,
        minute=0,
        id="daily_digest",
    )

    scheduler.start()
    logger.info("스케줄러 시작: 한국 월~금 20시, 나스닥 화~토 8시, 뉴스딥다이브 매일 9시, 이슈딥다이브 매일 10/15/21시, 종목딥다이브 매일 11시, 부동산 월 7시, 다이제스트 매일 22시")
    return scheduler
