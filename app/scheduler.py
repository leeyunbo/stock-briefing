"""스케줄러 - 매일 아침 브리핑 생성 및 발송."""

import asyncio
from datetime import date

from sqlalchemy import select

from app.collector.dart import fetch_disclosures
from app.collector.market import fetch_market_summary
from app.collector.news import fetch_stock_news, fetch_news_for_stocks
from app.summarizer import generate_briefing
from app.email_sender import send_briefing_to_subscribers
from app.database import async_session
from app.models import Subscriber, Briefing


async def run_briefing_pipeline() -> str | None:
    """전체 브리핑 파이프라인을 실행한다: 수집 → 요약 → 저장 → 발송."""
    today = date.today()
    print(f"[{today}] 브리핑 파이프라인 시작...")

    # 1. 데이터 수집 (병렬)
    market_data, disclosures, news = await asyncio.gather(
        fetch_market_summary(),
        fetch_disclosures(),
        fetch_stock_news(),
    )
    print(f"  수집 완료: 공시 {len(disclosures)}건, 뉴스 {len(news)}건")

    # 1-2. 코스피 TOP10 중 등락률 큰 종목 뉴스 추가 수집
    mover_names = [
        s["name"] for s in market_data.get("kospi_top10", [])
        if abs(float(s.get("change_pct", "0").replace(",", ""))) >= 2.0
    ]
    stock_news = await fetch_news_for_stocks(mover_names)
    print(f"  종목별 뉴스 수집: {len(stock_news)}종목")

    # 2. AI 요약
    briefing_html = generate_briefing(market_data, disclosures, news, stock_news)
    title = f"{today.strftime('%Y년 %m월 %d일')} 주식 아침 브리핑"
    print(f"  요약 완료: {title}")

    # 3. DB 저장
    async with async_session() as db:
        briefing = Briefing(
            date=today.isoformat(),
            title=title,
            content_html=briefing_html,
        )
        db.add(briefing)
        await db.commit()

        # 4. 이메일 발송
        result = await db.execute(select(Subscriber.email).where(Subscriber.is_active == True))
        emails = [row[0] for row in result.all()]

    if emails:
        email_html = _wrap_email_template(title, briefing_html)
        results = send_briefing_to_subscribers(emails, title, email_html)
        print(f"  발송 완료: 성공 {results['success']}, 실패 {results['fail']}")
    else:
        print("  구독자 없음 - 발송 건너뜀")

    return briefing_html


def _wrap_email_template(title: str, content_html: str) -> str:
    """브리핑 HTML을 이메일 템플릿으로 감싼다."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 8px; margin-bottom: 20px;">
        <h1 style="color: white; margin: 0; font-size: 20px;">{title}</h1>
    </div>
    <div style="line-height: 1.7;">
        {content_html}
    </div>
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Stock Briefing - AI 주식 아침 브리핑<br>
        구독을 원하지 않으시면 이 이메일에 답장해주세요.
    </p>
</body>
</html>"""


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
    print("스케줄러 시작: 평일 매일 아침 7시 브리핑 발송")
    return scheduler
