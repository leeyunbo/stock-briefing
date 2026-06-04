"""웹 리서치 레이어 — Claude CLI(WebSearch 내장)로 정성적 투자 인사이트를 수집한다.

숫자(시세·재무)는 구조화 API가 담당하고, 여기서는 '웹에서 긁어온 좋은 인사이트'를 담당한다:
애널리스트 의견·목표주가, 최근 중대 이벤트, 산업/실적 동향, 거시 이벤트 캘린더.

ai_provider 설정과 무관하게 항상 ClaudeCliProvider(WebSearch on)를 직접 쓴다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from asyncio import to_thread

from app.summarizer import ClaudeCliProvider

logger = logging.getLogger(__name__)

# 웹 검색을 충분히 돌릴 수 있게 넉넉한 타임아웃
_RESEARCH_TIMEOUT = 600

RESEARCH_SYSTEM = """당신은 증권 리서치 애널리스트예요. 반드시 웹을 검색해서 최신 정보를 확인하고,
중장기 투자자에게 도움이 되는 핵심 인사이트만 골라 정리해요.

[원칙]
- 추측·일반론 금지. 웹 검색으로 *확인된 사실*만. 확인 안 되면 '확인된 정보 없음'이라고 쓰세요.
- 모든 항목에 출처(매체명/기관)를 괄호로 명시. 가능하면 날짜도.
- 오래된 정보 말고 가능한 최신(최근 몇 주). 과장·홍보성 표현 금지.
- 한국어, 간결한 불릿. 분량보다 밀도."""


def _provider() -> ClaudeCliProvider:
    return ClaudeCliProvider(timeout=_RESEARCH_TIMEOUT)


def _call(user: str, tries: int = 3) -> str:
    """CLI 웹 리서치 호출 + 일시 실패(빈 stderr·한도) 백오프 재시도."""
    last: Exception | None = None
    for i in range(tries):
        try:
            out = _provider().call(RESEARCH_SYSTEM, user)
            if out.strip():
                return out
            last = RuntimeError("빈 응답")
        except Exception as e:
            last = e
        logger.warning("CLI 리서치 시도 %d/%d 실패: %s", i + 1, tries, last)
        time.sleep(5 * (i + 1))
    raise last or RuntimeError("리서치 실패")


def research_stock(name: str, ticker: str) -> str:
    """종목 1개를 웹 리서치해 인사이트를 반환한다 (동기)."""
    user = f"""'{name}'({ticker}) 종목을 웹에서 조사해서 중장기 투자 관점으로 정리해줘.

1. *애널리스트 뷰* — 최근 투자의견·목표주가 변화 (상향/하향, 어느 증권사/기관)
2. *최근 이벤트* — 2~4주 내 중대한 뉴스 (실적, 수주·계약, 규제, 경영, 신제품 등)
3. *thesis 체크* — 산업/실적 동향 중 중장기 투자 논거에 영향 주는 요인 (호재/악재 균형 있게)

각 항목 1~3줄, 출처 명시. 확인 안 되는 항목은 '확인된 정보 없음'."""
    try:
        out = _call(user)
        logger.info("웹 리서치 완료: %s (%d자)", ticker, len(out))
        return out
    except Exception as e:
        logger.warning("웹 리서치 실패 (%s): %s", ticker, e)
        return ""


def research_market() -> str:
    """거시·시장 상황 + 이벤트 캘린더를 웹 리서치한다 (동기)."""
    user = """오늘 기준 글로벌·한국 증시의 거시 상황과 앞으로의 일정을 웹에서 조사해 정리해줘.

1. *시장 레짐* — 현재 시장을 움직이는 핵심 거시 요인 (연준·금리 경로, 인플레, 달러, 지정학)
2. *이번 주 이벤트 캘린더* — 예정된 주요 실적 발표, 경제지표(CPI·고용·FOMC 등), 정책 일정
3. *주목 테마* — 시장에서 지금 가장 주목받는 투자 테마·내러티브

각 항목 출처와 날짜 명시. 확인 안 되면 생략."""
    try:
        out = _call(user)
        logger.info("거시 웹 리서치 완료 (%d자)", len(out))
        return out
    except Exception as e:
        logger.warning("거시 웹 리서치 실패: %s", e)
        return ""


def research_themes(theme_names: list[str]) -> str:
    """테마들의 최신 내러티브를 한 번에 웹 리서치한다 (동기)."""
    themes = ", ".join(theme_names)
    user = f"""다음 투자 테마들의 *최신 동향*을 웹에서 조사해 테마별로 1~2줄씩 정리해줘: {themes}

각 테마마다: 지금 이 테마를 움직이는 핵심 동인(수요·정책·기술 변화)과 중장기 방향성.
출처 명시. 단기 주가 등락 말고 구조적 흐름 중심."""
    try:
        out = _call(user)
        logger.info("테마 웹 리서치 완료 (%d자)", len(out))
        return out
    except Exception as e:
        logger.warning("테마 웹 리서치 실패: %s", e)
        return ""


async def gather_research(
    watchlist: list[tuple[str, str]],
    theme_names: list[str],
) -> dict:
    """거시 + 테마 + 종목별 웹 리서치를 동시에 수행한다.

    Returns: {"market": str, "themes": str, "stocks": {ticker: str}}
    """
    logger.info("웹 리서치 시작: 종목 %d개 + 거시 + 테마", len(watchlist))
    market_task = to_thread(research_market)
    themes_task = to_thread(research_themes, theme_names)
    stock_tasks = [to_thread(research_stock, name, ticker) for ticker, name in watchlist]

    market, themes, *stocks = await asyncio.gather(
        market_task, themes_task, *stock_tasks, return_exceptions=True
    )

    def _ok(x) -> str:
        return x if isinstance(x, str) else ""

    stock_map = {watchlist[i][0]: _ok(s) for i, s in enumerate(stocks)}
    return {"market": _ok(market), "themes": _ok(themes), "stocks": stock_map}
