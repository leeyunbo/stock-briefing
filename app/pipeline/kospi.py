"""국내주식 브리핑 파이프라인 — 각 단계가 독립 함수, 데이터 클래스로 연결."""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.collector.dart import Disclosure, fetch_disclosures
from app.collector.market import MarketSummary, fetch_market_summary
from app.collector.news import NewsArticle, fetch_news_for_stocks, fetch_stock_news
from app.collector.snapshot import (
    save_kospi_snapshot,
    fetch_index_history,
    fetch_latest_nasdaq,
)
from app.core.models import IndexSnapshot
from app.core.models import BriefingType
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.summarizer import generate_briefing
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)

# ── 공시 키워드 필터링 ──

_DISCLOSURE_KEYWORDS = [
    "자기주식", "유상증자", "무상증자", "배당", "합병", "분할",
    "최대주주", "주식교환", "공개매수", "전환사채", "신주인수권",
    "자본감소", "해산", "상장폐지", "횡령", "배임",
]

_DISCLOSURE_FALLBACK_COUNT = 5


def _filter_disclosures(disclosures: list[Disclosure]) -> list[Disclosure]:
    """개인투자자 관련 키워드가 포함된 공시만 필터링한다."""
    if not disclosures:
        return disclosures
    filtered = [
        d for d in disclosures
        if any(kw in d.report_nm for kw in _DISCLOSURE_KEYWORDS)
    ]
    return filtered if filtered else disclosures[:_DISCLOSURE_FALLBACK_COUNT]


# ── 단계 간 전달 데이터 ──


@dataclass
class CollectedData:
    """수집 단계의 결과물."""

    market: MarketSummary
    disclosures: list[Disclosure]
    news: list[NewsArticle]
    stock_news: dict[str, list[NewsArticle]] = field(default_factory=dict)
    is_market_closed: bool = False
    index_history: list[IndexSnapshot] = field(default_factory=list)
    nasdaq_overnight: list[IndexSnapshot] = field(default_factory=list)


class KospiContext(PipelineContext, total=False):
    """KOSPI 파이프라인 컨텍스트."""

    collected: CollectedData


# ── 파이프라인 단계 (각각 독립 함수) ──


def _is_market_closed_yesterday(market_date_str: str) -> bool:
    """시장 데이터 날짜가 전날이 아니면 휴장으로 판단한다."""
    if not market_date_str:
        return False
    market_date = date.fromisoformat(market_date_str)
    yesterday = date.today() - timedelta(days=1)
    return market_date < yesterday


async def collect_data() -> CollectedData:
    """1단계: 시장/공시/뉴스 데이터를 병렬 수집한다."""
    try:
        market = await fetch_market_summary()
    except Exception as e:
        logger.error("시장 데이터 수집 실패: %s", e)
        market = MarketSummary()

    try:
        await save_kospi_snapshot(market)
    except Exception as e:
        logger.warning("KOSPI 스냅샷 저장 실패 (무시): %s", e)

    index_history: list[IndexSnapshot] = []
    nasdaq_overnight: list[IndexSnapshot] = []
    try:
        index_history = await fetch_index_history(["kospi", "kosdaq"])
    except Exception as e:
        logger.warning("과거 추이 조회 실패 (무시): %s", e)
    try:
        nasdaq_overnight = await fetch_latest_nasdaq()
    except Exception as e:
        logger.warning("전일 나스닥 조회 실패 (무시): %s", e)

    is_closed = _is_market_closed_yesterday(market.date)

    if is_closed:
        logger.info("전일 휴장 감지 (market.date=%s) — 뉴스만 수집", market.date)
        try:
            news = await fetch_stock_news()
        except Exception as e:
            logger.error("뉴스 수집 실패: %s", e)
            news = []
        return CollectedData(
            market=market,
            disclosures=[],
            news=news,
            is_market_closed=True,
            index_history=index_history,
            nasdaq_overnight=nasdaq_overnight,
        )

    results = await asyncio.gather(
        fetch_disclosures(),
        fetch_stock_news(),
        return_exceptions=True,
    )

    disclosures = results[0] if not isinstance(results[0], Exception) else []
    news = results[1] if not isinstance(results[1], Exception) else []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("수집 단계 %d 실패: %s", i, result)

    disclosures = _filter_disclosures(disclosures)
    logger.info("수집 완료: 공시 %d건, 뉴스 %d건", len(disclosures), len(news))

    movers = sorted(
        [s for s in market.kospi_top10
         if abs(float(s.change_pct.replace(",", "") or "0")) >= 2.0],
        key=lambda s: abs(float(s.change_pct.replace(",", "") or "0")),
        reverse=True,
    )[:5]
    mover_names = [s.name for s in movers]
    stock_news = await fetch_news_for_stocks(mover_names)
    logger.info("종목별 뉴스 수집: %d종목", len(stock_news))

    return CollectedData(
        market=market,
        disclosures=disclosures,
        news=news,
        stock_news=stock_news,
        index_history=index_history,
        nasdaq_overnight=nasdaq_overnight,
    )


def summarize(data: CollectedData) -> BriefingResult:
    """2단계: 수집 데이터를 AI로 요약한다."""
    seo = generate_briefing(
        data.market, data.disclosures, data.news, data.stock_news,
        is_market_closed=data.is_market_closed,
        index_history=data.index_history,
        nasdaq_overnight=data.nasdaq_overnight,
    )
    title = seo.title or f"{date.today().strftime('%Y년 %m월 %d일')} 국내주식 마감 브리핑"
    logger.info("요약 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword)


# ── KOSPI 스텝 함수 ──


async def collect_kospi_data(ctx: KospiContext) -> None:
    """시장/공시/뉴스 데이터를 수집한다."""
    ctx["collected"] = await collect_data()


async def summarize_kospi(ctx: KospiContext) -> None:
    """수집 데이터를 AI로 요약한다."""
    ctx["result"] = await to_thread(summarize, ctx["collected"])


KOSPI_STEPS = [
    collect_kospi_data,
    summarize_kospi,
    deliver,
]


# ── 오케스트레이터 ──


async def run_pipeline(email_to: list[str] | None = []) -> str:
    """전체 파이프라인: 수집 → 요약 → 저장 → 발송 — 스텝 기반.

    Args:
        email_to: 발송 대상. None=전체 구독자, []=발송 안 함, ["a@b.com"]=특정 주소.
    """
    logger.info("브리핑 파이프라인 시작: %s", date.today())
    ctx: KospiContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "kospi",
        "briefing_type": BriefingType.KOSPI,
    }
    await run_steps(KOSPI_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
