"""스케줄러 - 매일 아침 브리핑 생성 및 발송."""

import asyncio
import re
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
        email_html = _wrap_email_template(title, briefing_html)
        results = send_briefing_to_subscribers(emails, title, email_html)
        print(f"  발송 완료: 성공 {results['success']}, 실패 {results['fail']}")
    else:
        print("  구독자 없음 - 발송 건너뜀")

    return briefing_html


def _style_content_html(html: str) -> str:
    """AI가 생성한 HTML에 다크 테마 인라인 스타일을 자동 적용한다."""
    # <h2> → 섹션 헤더 (왼쪽 파란 바 + 흰 볼드)
    html = re.sub(
        r'<h2>(.*?)</h2>',
        r'<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top: 28px; margin-bottom: 14px;">'
        r'<tr><td style="width: 4px; background-color: #3182F6; border-radius: 2px;"></td>'
        r'<td style="padding-left: 12px; font-size: 17px; font-weight: 700; color: #FFFFFF; line-height: 1.4;">\1</td>'
        r'</tr></table>',
        html,
    )
    # <ul> → 리스트 컨테이너
    html = html.replace('<ul>', '<ul style="list-style: none; padding: 0; margin: 0 0 8px 0;">')
    # <li> → 리스트 아이템 (다크 카드)
    html = re.sub(
        r'<li(?:\s[^>]*)?>',
        '<li style="background-color: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; font-size: 14px; line-height: 1.75; color: rgba(255,255,255,0.75);">',
        html,
    )
    # <strong> → 흰색 볼드
    html = html.replace('<strong>', '<strong style="color: #FFFFFF; font-weight: 700;">')
    # <p> → 본문 텍스트
    html = re.sub(
        r'<p(?:\s[^>]*)?>',
        '<p style="font-size: 14px; line-height: 1.75; color: rgba(255,255,255,0.65); margin: 0 0 12px 0;">',
        html,
    )
    return html


def _wrap_email_template(title: str, content_html: str) -> str:
    """브리핑 HTML을 다크 테마 이메일 템플릿으로 감싼다. 네이버/Gmail 호환."""
    styled = _style_content_html(content_html)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #F4F5F7; -webkit-text-size-adjust: 100%;">
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #F4F5F7; font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;">
<tr><td align="center" style="padding: 24px 16px;">

<!-- Main Card -->
<table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; background-color: #111113; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.06);">

    <!-- Header -->
    <tr>
        <td style="padding: 32px 32px 0 32px;">
            <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                    <td style="padding-bottom: 10px;">
                        <table cellpadding="0" cellspacing="0" border="0"><tr>
                            <td style="width: 8px; height: 8px; background-color: #3182F6; border-radius: 50%;"></td>
                            <td style="padding-left: 8px; font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.4); letter-spacing: -0.3px;">Stock Briefing</td>
                        </tr></table>
                    </td>
                </tr>
                <tr>
                    <td style="font-size: 22px; font-weight: 800; color: #FFFFFF; line-height: 1.35; padding-bottom: 6px; letter-spacing: -0.8px;">
                        {title}
                    </td>
                </tr>
                <tr>
                    <td style="font-size: 13px; color: rgba(255,255,255,0.3); padding-bottom: 24px; letter-spacing: -0.2px;">
                        AI가 정리한 오늘의 시장 요약
                    </td>
                </tr>
                <tr>
                    <td style="border-bottom: 1px solid rgba(255,255,255,0.06);"></td>
                </tr>
            </table>
        </td>
    </tr>

    <!-- Content -->
    <tr>
        <td style="padding: 8px 32px 32px 32px; color: rgba(255,255,255,0.75); font-size: 14px; line-height: 1.75;">
            {styled}
        </td>
    </tr>

</table>
<!-- End Main Card -->

<!-- Footer -->
<table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; margin-top: 20px;">
    <tr>
        <td align="center" style="padding: 8px 0;">
            <span style="font-size: 11px; color: #8B95A1;">Stock Briefing &middot; AI 주식 아침 브리핑</span>
        </td>
    </tr>
    <tr>
        <td align="center" style="padding: 0 0 8px 0;">
            <span style="font-size: 11px; color: #B0B8C1;">구독을 원하지 않으시면 이 이메일에 답장해주세요</span>
        </td>
    </tr>
</table>

</td></tr>
</table>
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
