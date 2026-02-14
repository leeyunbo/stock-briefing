"""브리핑 파이프라인 — 각 단계가 독립 함수, 데이터 클래스로 연결.

스프링의 서비스 레이어 분리와 동일:
- collect_data()  → CollectorService
- summarize()     → SummarizerService
- save_briefing() → BriefingRepository
- send_emails()   → EmailService
- run_pipeline()  → Orchestrator (각 서비스를 순서대로 호출)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.collector.dart import Disclosure, fetch_disclosures
from app.collector.market import MarketSummary, fetch_market_summary
from app.collector.news import NewsArticle, fetch_news_for_stocks, fetch_stock_news
from app.database import async_session
from app.email_sender import send_briefing_to_subscribers
from app.email_template import render_email
from app.models import Briefing, Subscriber
from app.summarizer import generate_briefing

logger = logging.getLogger(__name__)


# ── 단계 간 전달 데이터 (스프링의 서비스 간 DTO) ──


@dataclass
class CollectedData:
    """수집 단계의 결과물."""

    market: MarketSummary
    disclosures: list[Disclosure]
    news: list[NewsArticle]
    stock_news: dict[str, list[NewsArticle]] = field(default_factory=dict)


@dataclass
class BriefingResult:
    """요약 단계의 결과물."""

    title: str
    html: str


# ── 파이프라인 단계 (각각 독립 함수) ──


async def collect_data() -> CollectedData:
    """1단계: 시장/공시/뉴스 데이터를 병렬 수집한다."""
    market, disclosures, news = await asyncio.gather(
        fetch_market_summary(),
        fetch_disclosures(),
        fetch_stock_news(),
    )
    logger.info("수집 완료: 공시 %d건, 뉴스 %d건", len(disclosures), len(news))

    # 등락률 큰 종목 뉴스 추가 수집
    mover_names = [
        s.name for s in market.kospi_top10
        if abs(float(s.change_pct.replace(",", "") or "0")) >= 2.0
    ]
    stock_news = await fetch_news_for_stocks(mover_names)
    logger.info("종목별 뉴스 수집: %d종목", len(stock_news))

    return CollectedData(
        market=market,
        disclosures=disclosures,
        news=news,
        stock_news=stock_news,
    )


def summarize(data: CollectedData) -> BriefingResult:
    """2단계: 수집 데이터를 AI로 요약한다."""
    html = generate_briefing(data.market, data.disclosures, data.news, data.stock_news)
    title = f"{date.today().strftime('%Y년 %m월 %d일')} 주식 아침 브리핑"
    logger.info("요약 완료: %s", title)
    return BriefingResult(title=title, html=html)


async def save_briefing(result: BriefingResult) -> None:
    """3단계: 브리핑을 DB에 저장한다 (같은 날 재실행 시 업데이트)."""
    today = date.today().isoformat()
    async with async_session() as db:
        existing = await db.execute(select(Briefing).where(Briefing.date == today))
        briefing = existing.scalar_one_or_none()
        if briefing:
            briefing.title = result.title
            briefing.content_html = result.html
        else:
            db.add(Briefing(date=today, title=result.title, content_html=result.html))
        await db.commit()


async def send_emails(result: BriefingResult) -> None:
    """4단계: 구독자에게 이메일을 발송한다."""
    async with async_session() as db:
        rows = await db.execute(select(Subscriber.email).where(Subscriber.is_active == True))
        emails = [row[0] for row in rows.all()]

    if not emails:
        logger.info("구독자 없음 — 발송 건너뜀")
        return

    email_html = render_email(result.title, result.html)
    results = await send_briefing_to_subscribers(emails, result.title, email_html)
    logger.info("발송 완료: 성공 %d, 실패 %d", results["success"], results["fail"])


# ── 오케스트레이터 ──


async def run_pipeline() -> str:
    """전체 파이프라인: 수집 → 요약 → 저장 → 발송."""
    logger.info("브리핑 파이프라인 시작: %s", date.today())

    data = await collect_data()
    result = summarize(data)
    await save_briefing(result)
    await send_emails(result)

    return result.html
