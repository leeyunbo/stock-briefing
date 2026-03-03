"""종목 딥다이브 파이프라인 — 개별 종목 심층 분석.

수동 모드: ticker 지정 → detect_market → 수집 → 기사 생성 → 발행
자동 모드: ticker=None → 시장 스캔 → LLM 종목 선정 → 수집 → 기사 생성 → 발행
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date
from typing import Any

from app.collector.kr_research_models import KRStockResearchData
from app.collector.kr_stock_research import detect_market, fetch_kr_stock_research
from app.collector.market import fetch_market_summary
from app.collector.market_scan import fetch_macro_indicators, scan_market
from app.collector.research_models import MacroIndicators, MarketScanData, StockResearchData
from app.collector.stock_research import fetch_stock_research
from app.core.models import BriefingType
from app.pipeline.base import BriefingResult, PipelineContext, deliver, run_steps
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


class StockDeepDiveContext(PipelineContext, total=False):
    """종목 딥다이브 파이프라인 컨텍스트."""

    ticker: str | None  # None = 자동 선정
    market: str  # "KR" / "US"
    why_picked: str
    scan: MarketScanData
    macro: MacroIndicators
    kr_market_text: str
    kr_data: KRStockResearchData
    us_data: StockResearchData


# ── 스텝 함수 ──


async def collect_market_context(ctx: StockDeepDiveContext) -> None:
    """Stage 1: 자동 모드일 때 시장 컨텍스트를 수집한다."""
    if ctx.get("ticker"):
        logger.info("[종목딥다이브 Stage 1] 수동 모드 — 시장 스캔 스킵")
        return

    logger.info("[종목딥다이브 Stage 1] 자동 모드 — 시장 스캔 + 매크로 + KR 시장 수집...")
    scan_data, macro_data, kr_market = await asyncio.gather(
        scan_market(),
        fetch_macro_indicators(),
        fetch_market_summary(),
    )
    ctx["scan"] = scan_data
    ctx["macro"] = macro_data

    # KR 시장 텍스트 구성
    kr_parts = []
    if kr_market.kospi:
        kr_parts.append(f"KOSPI: {kr_market.kospi.close} ({kr_market.kospi.change_pct}%)")
    if kr_market.kosdaq:
        kr_parts.append(f"KOSDAQ: {kr_market.kosdaq.close} ({kr_market.kosdaq.change_pct}%)")
    if kr_market.kospi_top10:
        kr_parts.append("시총 TOP10:")
        for s in kr_market.kospi_top10:
            kr_parts.append(f"  - {s.name}: {s.close}원 ({s.change_pct}%)")
    ctx["kr_market_text"] = "\n".join(kr_parts) if kr_parts else "KR 시장 데이터 없음"

    logger.info("[종목딥다이브 Stage 1] 스캔 완료: 뉴스 %d건", len(scan_data.market_news))


async def pick_stock(ctx: StockDeepDiveContext) -> None:
    """Stage 2: 수동이면 마켓 판별만, 자동이면 LLM으로 종목 선정."""
    ticker = ctx.get("ticker")

    if ticker:
        # 수동 모드: 마켓 판별만
        ctx["market"] = detect_market(ticker)
        ctx["why_picked"] = "수동 지정"
        logger.info("[종목딥다이브 Stage 2] 수동 모드: %s → %s", ticker, ctx["market"])
        return

    # 자동 모드: LLM 종목 선정
    logger.info("[종목딥다이브 Stage 2] 자동 모드 — LLM 종목 선정 중...")
    from app.prompts.stock_deep_dive import call_pick_stock

    scan = ctx.get("scan")
    macro = ctx.get("macro")
    scan_text = scan.model_dump_json(indent=2) if scan else "{}"
    macro_text = macro.model_dump_json(indent=2) if macro else "{}"
    kr_market_text = ctx.get("kr_market_text", "")

    result = await to_thread(
        call_pick_stock, scan_text, macro_text, kr_market_text,
        run_id=ctx["run_id"],
    )
    ctx["ticker"] = result["ticker"]
    ctx["market"] = result["market"]
    ctx["why_picked"] = result.get("why_picked", "")
    logger.info("[종목딥다이브 Stage 2] 선정: %s (%s) — %s",
                ctx["ticker"], ctx["market"], ctx["why_picked"])


async def collect_stock_data(ctx: StockDeepDiveContext) -> None:
    """Stage 3: KR 또는 US 종목 데이터를 수집한다."""
    ticker = ctx["ticker"]
    market = ctx["market"]

    logger.info("[종목딥다이브 Stage 3] %s 종목 데이터 수집: %s", market, ticker)

    if market == "KR":
        kr_data = await fetch_kr_stock_research(ticker)
        ctx["kr_data"] = kr_data
        logger.info("[종목딥다이브 Stage 3] KR 수집 완료: %s", kr_data.profile.name)
    else:
        us_data = await fetch_stock_research(ticker)
        ctx["us_data"] = us_data
        logger.info("[종목딥다이브 Stage 3] US 수집 완료: %s", us_data.profile.name)


async def generate_article(ctx: StockDeepDiveContext) -> None:
    """Stage 4: 수집된 데이터로 딥리서치 기사를 생성한다."""
    logger.info("[종목딥다이브 Stage 4] 기사 작성 중...")

    if ctx["market"] == "KR":
        from app.prompts.stock_deep_dive import generate_stock_article_kr
        result = await to_thread(
            generate_stock_article_kr, ctx["kr_data"], run_id=ctx["run_id"],
        )
    else:
        from app.prompts.stock_deep_dive import generate_stock_article_us
        result = await to_thread(
            generate_stock_article_us, ctx["us_data"], run_id=ctx["run_id"],
        )

    ctx["result"] = result
    logger.info("[종목딥다이브 Stage 4] 기사 완료: %s", result.title)


async def render_charts(ctx: StockDeepDiveContext) -> None:
    """Stage 5: 본문의 차트 지시자를 실제 차트 이미지로 교체한다.

    issue_dive의 render_charts와 동일한 로직.
    """
    from app.publishing.chart import parse_chart_directives, render_chart
    from app.publishing.wordpress import _upload_media, _slugify

    import base64
    import httpx
    from app.core.config import get_settings

    result: BriefingResult = ctx["result"]
    directives = parse_chart_directives(result.html)

    if not directives:
        logger.info("[종목딥다이브 Stage 5] 차트 지시자 없음 — 스킵")
        return

    logger.info("[종목딥다이브 Stage 5] %d개 차트 렌더링 중...", len(directives))

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
            html = html.replace(directive["placeholder"], "")
            continue

        title_text = directive["params"].get("title", f"chart-{i}")

        if has_wp:
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
    logger.info("[종목딥다이브 Stage 5] %d개 차트 삽입 완료", chart_count)


STOCK_DEEP_DIVE_STEPS = [
    collect_market_context,
    pick_stock,
    collect_stock_data,
    generate_article,
    render_charts,
    deliver,
]


async def run_stock_deep_dive_pipeline(
    ticker: str | None = None,
    email_to: list[str] | None = [],
) -> str:
    """종목 딥다이브 파이프라인 — 스텝 기반.

    Args:
        ticker: 분석할 종목 (None이면 자동 선정)
        email_to: 이메일 수신자 (빈 리스트면 이메일 미발송)
    """
    logger.info("종목 딥다이브 파이프라인 시작: %s, ticker=%s", date.today(), ticker)
    ctx: StockDeepDiveContext = {
        "run_id": generate_run_id(),
        "email_to": email_to,
        "pipeline": "stock_deep_dive",
        "briefing_type": BriefingType.STOCK_DEEP_DIVE,
        "ticker": ticker or None,
    }
    await run_steps(STOCK_DEEP_DIVE_STEPS, ctx)
    result = ctx.get("result")
    return result.html if result else ""
