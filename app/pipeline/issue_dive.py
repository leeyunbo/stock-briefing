"""이슈 딥다이브 파이프라인 — 단일 이슈를 깊게 파는 피처 기사.

collect → dedup → pick_top_issue (LLM #1) → research_issue → generate_article (LLM #2) → deliver
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.market_scan import fetch_macro_indicators, scan_market
from app.collector.news import NewsArticle, fetch_news
from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.collector.stock_research import screen_candidates
from app.core.models import BriefingType
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.prompts.issue_dive import generate_issue_dive_article, pick_top_issue
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class IssueDiveContext(PipelineContext, total=False):
    """이슈 딥다이브 파이프라인 컨텍스트."""

    scan: MarketScanData
    macro: MacroIndicators
    issue: dict[str, Any]
    additional_news: list[NewsArticle]
    screened: list[CandidateScreenData]


# ── 스텝 함수 ──


async def collect_market_data(ctx: IssueDiveContext) -> None:
    """Stage 1: 시장 스캔 + 매크로 지표를 병렬 수집한다."""
    logger.info("[이슈딥다이브 Stage 1] 시장 스캔 + 매크로 지표 수집...")
    scan_data, macro_data = await asyncio.gather(scan_market(), fetch_macro_indicators())
    logger.info("[이슈딥다이브 Stage 1] 스캔 완료: 뉴스 %d건, 매크로 VIX=%s",
                len(scan_data.market_news), macro_data.vix)
    ctx["scan"] = scan_data
    ctx["macro"] = macro_data


async def dedup_issue_news(ctx: IssueDiveContext) -> None:
    """Stage 2: 별도 컬렉션으로 시맨틱 중복 제거."""
    from app.collector.dedup import dedup_news
    scan = ctx["scan"]
    scan.market_news = dedup_news(
        scan.market_news, lambda n: f"{n.headline} {n.summary}",
        "issue_dive_news", run_id=ctx["run_id"], pipeline="issue_dive",
    )
    if not scan.market_news:
        logger.info("새로운 뉴스 없음 — 이슈 딥다이브 스킵")
        ctx["skip"] = True


async def pick_issue(ctx: IssueDiveContext) -> None:
    """Stage 3: LLM #1에게 가장 중요한 이슈 1개를 선정한다."""
    logger.info("[이슈딥다이브 Stage 3] 이슈 선정 중...")
    issue = await to_thread(pick_top_issue, ctx["scan"], ctx["macro"], run_id=ctx["run_id"])
    logger.info("[이슈딥다이브 Stage 3] 선정 이슈: %s", issue.get("headline", ""))
    ctx["issue"] = issue


async def research_issue(ctx: IssueDiveContext) -> None:
    """Stage 4: 선정된 이슈의 키워드로 추가 뉴스 수집 + 관련 종목 스크리닝."""
    issue = ctx["issue"]
    keywords = issue.get("search_keywords", [])
    tickers = issue.get("related_tickers", [])

    # 키워드 기반 추가 뉴스 수집 (5 키워드 × 10건)
    logger.info("[이슈딥다이브 Stage 4] 추가 뉴스 수집: %d 키워드...", len(keywords))
    news_tasks = [fetch_news(query=kw, count=10) for kw in keywords[:5]]
    news_results = await asyncio.gather(*news_tasks)

    # 중복 링크 제거하여 합치기
    all_news: list[NewsArticle] = []
    seen_links: set[str] = set()
    for articles in news_results:
        for article in articles:
            if article.link not in seen_links:
                seen_links.add(article.link)
                all_news.append(article)

    logger.info("[이슈딥다이브 Stage 4] 추가 뉴스 %d건 수집", len(all_news))
    ctx["additional_news"] = all_news

    # 관련 종목 재무 스크리닝
    logger.info("[이슈딥다이브 Stage 4] %d개 종목 재무 스크리닝...", len(tickers))
    screened = await screen_candidates(tickers)
    logger.info("[이슈딥다이브 Stage 4] 스크리닝 완료: %d개 종목 데이터 확보", len(screened))
    ctx["screened"] = screened


async def generate_article(ctx: IssueDiveContext) -> None:
    """Stage 5: 수집한 심층 자료로 장문 피처 기사를 생성한다."""
    logger.info("[이슈딥다이브 Stage 5] 피처 기사 작성 중...")
    result = await to_thread(
        generate_issue_dive_article,
        ctx["issue"], ctx["additional_news"], ctx["screened"],
        ctx["scan"], ctx["macro"],
        run_id=ctx["run_id"],
    )
    ctx["result"] = result


async def render_charts(ctx: IssueDiveContext) -> None:
    """Stage 6: 본문의 차트 지시자를 실제 차트 이미지로 교체한다."""
    from app.publishing.chart import parse_chart_directives, render_chart
    from app.publishing.wordpress import _upload_media, _slugify

    import base64
    import httpx
    from app.core.config import get_settings

    result: BriefingResult = ctx["result"]
    directives = parse_chart_directives(result.html)

    if not directives:
        logger.info("[이슈딥다이브 Stage 6] 차트 지시자 없음 — 스킵")
        return

    logger.info("[이슈딥다이브 Stage 6] %d개 차트 렌더링 중...", len(directives))

    # WordPress 인증 (이미지 업로드용)
    wp_url = get_settings().wp_url
    wp_user = get_settings().wp_user
    wp_pass = get_settings().wp_app_password
    has_wp = bool(wp_url and wp_user and wp_pass)

    if has_wp:
        credentials = f"{wp_user}:{wp_pass}"
        token = base64.b64encode(credentials.encode()).decode()
        wp_headers = {"Authorization": f"Basic {token}"}

    html = result.html
    chart_count = 0

    for i, directive in enumerate(directives):
        chart_bytes = await to_thread(render_chart, directive)
        if not chart_bytes:
            # 렌더링 실패 시 지시자 제거
            html = html.replace(directive["placeholder"], "")
            continue

        title_text = directive["params"].get("title", f"chart-{i}")

        if has_wp:
            # WordPress에 업로드
            async with httpx.AsyncClient(timeout=30, headers=wp_headers) as client:
                filename = f"{_slugify(result.title)}-chart-{i}.png"
                upload = await _upload_media(client, chart_bytes, filename, alt_text=title_text)
                if upload:
                    _, img_url = upload
                    img_tag = (
                        f'<figure style="margin:1.5rem 0;">'
                        f'<img src="{img_url}" alt="{title_text}" '
                        f'style="width:100%;height:auto;border-radius:12px;" />'
                        f'</figure>'
                    )
                    html = html.replace(directive["placeholder"], img_tag)
                    chart_count += 1
                    continue

        # WordPress 없으면 base64 인라인 (개발용)
        import base64 as b64
        b64_data = b64.b64encode(chart_bytes).decode()
        img_tag = (
            f'<figure style="margin:1.5rem 0;">'
            f'<img src="data:image/png;base64,{b64_data}" alt="{title_text}" '
            f'style="width:100%;height:auto;border-radius:12px;" />'
            f'</figure>'
        )
        html = html.replace(directive["placeholder"], img_tag)
        chart_count += 1

    result.html = html
    logger.info("[이슈딥다이브 Stage 6] %d개 차트 삽입 완료", chart_count)


ISSUE_DIVE_STEPS = [
    collect_market_data,
    dedup_issue_news,
    pick_issue,
    research_issue,
    generate_article,
    render_charts,
    deliver,
]


async def run_issue_dive_pipeline(email_to: list[str] | None = [], topic: dict | None = None) -> str:
    """이슈 딥다이브 파이프라인 — 스텝 기반.

    topic이 주어지면 시장 스캔/중복제거/이슈 선정을 건너뛰고
    바로 리서치 → 기사 생성으로 진행한다.
    """
    logger.info("이슈 딥다이브 파이프라인 시작: %s (topic=%s)", date.today(), topic.get("topic", "") if topic else "auto")
    ctx: IssueDiveContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "issue_dive",
        "briefing_type": BriefingType.ISSUE_DIVE,
    }
    if topic:
        ctx["issue"] = topic
        ctx["scan"] = MarketScanData()
        ctx["macro"] = MacroIndicators()
        steps = [research_issue, generate_article, render_charts, deliver]
    else:
        steps = ISSUE_DIVE_STEPS
    await run_steps(steps, ctx)
    result = ctx.get("result")
    return result.html if result else ""
