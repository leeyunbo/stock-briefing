"""스케줄러 - 매일 아침 브리핑 생성 및 발송."""

import asyncio
import logging
from datetime import date

from sqlalchemy import select

from app.collector.dart import fetch_disclosures
from app.collector.market import fetch_market_summary
from app.collector.news import fetch_stock_news, fetch_news_for_stocks
from app.database import async_session
from app.email_sender import send_briefing_to_subscribers
from app.email_template import render_email
from app.models import Subscriber, Briefing
from app.summarizer import generate_briefing

logger = logging.getLogger(__name__)


async def run_briefing_pipeline() -> str | None:
    """전체 브리핑 파이프라인을 실행한다: 수집 → 요약 → 저장 → 발송."""
    today = date.today()
    logger.info("브리핑 파이프라인 시작: %s", today)

    # 1. 데이터 수집 (병렬)
    market, disclosures, news = await asyncio.gather(
        fetch_market_summary(),
        fetch_disclosures(),
        fetch_stock_news(),
    )
    logger.info("수집 완료: 공시 %d건, 뉴스 %d건", len(disclosures), len(news))

    # 1-2. 코스피 TOP10 중 등락률 큰 종목 뉴스 추가 수집
    mover_names = [
        s.name for s in market.kospi_top10
        if abs(float(s.change_pct.replace(",", "") or "0")) >= 2.0
    ]
    stock_news = await fetch_news_for_stocks(mover_names)
    logger.info("종목별 뉴스 수집: %d종목", len(stock_news))

    # 2. AI 요약
    briefing_html = generate_briefing(market, disclosures, news, stock_news)
    title = f"{today.strftime('%Y년 %m월 %d일')} 주식 아침 브리핑"
    logger.info("요약 완료: %s", title)

    # 3. DB 저장 (같은 날 재실행 시 업데이트)
    async with async_session() as db:
        existing = await db.execute(select(Briefing).where(Briefing.date == today.isoformat()))
        briefing = existing.scalar_one_or_none()
        if briefing:
            briefing.title = title
            briefing.content_html = briefing_html
        else:
            briefing = Briefing(date=today.isoformat(), title=title, content_html=briefing_html)
            db.add(briefing)
        await db.commit()

        # 4. 이메일 발송
        result = await db.execute(select(Subscriber.email).where(Subscriber.is_active == True))
        emails = [row[0] for row in result.all()]

    if emails:
        email_html = render_email(title, briefing_html)
        results = send_briefing_to_subscribers(emails, title, email_html)
        logger.info("발송 완료: 성공 %d, 실패 %d", results["success"], results["fail"])
    else:
        logger.info("구독자 없음 — 발송 건너뜀")

    return briefing_html


def start_scheduler():
    """APScheduler로 매일 아침 7시 브리핑을 스케줄링한다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_briefing_pipeline,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="mon-fri",
        id="daily_briefing",
    )
    scheduler.start()
    logger.info("스케줄러 시작: 평일 매일 아침 7시 브리핑 발송")
    return scheduler
