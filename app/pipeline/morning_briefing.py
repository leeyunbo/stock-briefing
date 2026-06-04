"""개인 중장기 아침 Slack 브리핑 파이프라인.

scan(매크로·시세) + web research(인사이트) → 개요 합성 → 5인 의견 에이전트 → Slack 발송.
공개 블로그/이메일로는 나가지 않는다 (개인용).
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from datetime import date

from app.collector.theme_scan import scan_themes
from app.collector.themes import THEMES, WATCHLIST
from app.collector.web_research import gather_research
from app.prompts.morning_briefing import build_market_overview
from app.prompts.opinions import gather_opinions
from app.publishing.slack import deliver_to_slack
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)


def _build_opinion_context(overview: str, research: dict) -> str:
    """5인 에이전트에 넘길 '오늘의 정보' 묶음 (개요 + 웹 리서치 발췌)."""
    parts = [overview, "\n[참고 — 웹 리서치 발췌]"]
    if research.get("market"):
        parts.append("## 거시·이벤트\n" + research["market"][:1500])
    if research.get("themes"):
        parts.append("## 테마\n" + research["themes"][:1200])
    for ticker, text in (research.get("stocks") or {}).items():
        if text:
            parts.append(f"## {ticker}\n{text[:900]}")
    return "\n".join(parts)


async def run_morning_briefing_pipeline() -> None:
    """매일 아침 개인 시장 브리핑을 Slack으로 발송한다."""
    run_id = generate_run_id()
    logger.info("아침 브리핑 시작: %s (run_id=%s)", date.today(), run_id)

    # 구조화 시세 스캔 + 웹 리서치(인사이트)를 병렬로
    scan, research = await asyncio.gather(
        scan_themes(),
        gather_research(WATCHLIST, list(THEMES.keys())),
    )
    overview = await to_thread(build_market_overview, scan, research, run_id)

    # 메인이 모은 정보를 5인 의견 에이전트에 넘겨 각자 한 관점씩
    opinions = await gather_opinions(_build_opinion_context(overview, research))

    body = overview
    if opinions:
        body += "\n===\n💬 *5명의 시선*\n===\n" + "\n===\n".join(opinions)

    header = f"📈 {date.today().month}월 {date.today().day}일 아침 시장 브리핑"
    await deliver_to_slack(header, body, [])
    logger.info("아침 브리핑 완료: 의견 %d개", len(opinions))
