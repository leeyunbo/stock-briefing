"""개인 아침 Slack 브리핑 파이프라인.

scan(매크로+테마) → 핫 종목 스포트라이트(재무+기술+차트) → Slack 발송.
공개 블로그/이메일로는 나가지 않는다 (개인용).
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from datetime import date

from app.collector.spotlight import fetch_spotlight
from app.collector.theme_scan import scan_themes
from app.prompts.morning_briefing import build_market_overview, build_spotlight_analysis
from app.publishing.slack import deliver_to_slack
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


async def run_morning_briefing_pipeline() -> None:
    """매일 아침 개인 시장 브리핑을 Slack으로 발송한다."""
    run_id = generate_run_id()
    logger.info("아침 브리핑 시작: %s (run_id=%s)", date.today(), run_id)

    scan = await scan_themes()
    overview = await to_thread(build_market_overview, scan, run_id)

    spotlights: list[tuple[bytes | None, str, str]] = []
    for pick in scan.spotlight:
        sp = await fetch_spotlight(pick.ticker, pick.name)
        analysis = await to_thread(build_spotlight_analysis, sp, run_id)
        title = f"{sp.name} ({sp.ticker})"
        spotlights.append((sp.chart_png, title, analysis))

    header = f"📈 {date.today().month}월 {date.today().day}일 아침 시장 브리핑"
    await deliver_to_slack(header, overview, spotlights)
    logger.info("아침 브리핑 완료: 스포트라이트 %d종목", len(spotlights))
