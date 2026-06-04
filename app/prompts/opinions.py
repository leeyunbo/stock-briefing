"""5인 의견 에이전트 — 메인이 모은 정보를 받아 각자 한 관점씩 토스체로 코멘트한다.

메인 파이프라인은 '정보(개요 + 웹 리서치 요약)'만 넘기고, 5개 에이전트가 독립적으로
서로 다른 렌즈에서 의견을 낸다. 마지막 하나는 종합한 '내 생각'.
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread

from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)


TOSS_TONE = """[말투 — 토스(toss) 스타일: 일반인도 쉽게]
- 어려운 용어는 괄호로 풀어줘요. 예: PER(주가가 이익의 몇 배인지), 밸류에이션(주가가 비싼지 싼지).
- 따뜻하고 대화하듯 "~해요"체. 짧고 명료하게. 전문가인 척 금지.
- 숫자엔 맥락을 붙여요. 과장·홍보성 표현 금지."""

# (이모지, 이름, 렌즈 설명)
PERSONAS: list[tuple[str, str, str]] = [
    ("🐂", "낙관론자", "강세 관점이에요. 지금 좋게 볼 근거·기회를 찾아 말해요. 단 정보에 있는 근거로만, 무작정 띄우지 마세요."),
    ("🐻", "신중론자", "리스크 관점이에요. 조심할 점·약세 시나리오·놓치기 쉬운 위험을 짚어요."),
    ("💰", "가치투자자", "밸류·실적 관점이에요. 지금 가격이 싼지 비싼지, 실적 대비 매력적인지를 봐요."),
    ("🌍", "거시 전략가", "금리·환율·경기 같은 큰 흐름이 이 시장/종목에 뭘 의미하는지 봐요."),
    ("🤖", "내 생각", "위 정보를 종합한 균형 잡힌 결론이에요. 그래서 중장기 투자자가 오늘 뭘 하면 좋을지 한마디로 정리해요."),
]

_SYSTEM_TMPL = """당신은 '{name}' 관점의 투자 코멘테이터예요. {lens}

아래 '오늘의 시장 정보'를 읽고, 당신 관점에서 *핵심 의견 하나*를 3~4문장으로 줘요.
중장기 투자자 기준. 정보에 있는 사실만 쓰고, 없는 건 지어내지 마세요.

{tone}

[출력] Slack mrkdwn. 굵게 *별표 한 개*(** 금지). 첫 줄에 한 줄 요약(굵게), 그 아래 쉽게 풀어 설명."""


def _opine(emoji: str, name: str, lens: str, context: str) -> str:
    system = _SYSTEM_TMPL.format(name=name, lens=lens, tone=TOSS_TONE)
    provider = get_provider(pipeline="morning_briefing", stage=f"opinion:{name}")
    try:
        raw = provider.call(system, f"# 오늘의 시장 정보\n\n{context}")
        body = strip_code_block(raw).strip().replace("**", "*")
        logger.info("의견 완료: %s (%d자)", name, len(body))
        return f"{emoji} *{name}*\n{body}"
    except Exception as e:
        logger.warning("의견 생성 실패 (%s): %s", name, e)
        return ""


async def gather_opinions(context: str) -> list[str]:
    """5개 의견 에이전트를 동시에 돌려 mrkdwn 의견 리스트를 반환한다."""
    logger.info("5인 의견 에이전트 시작")
    results = await asyncio.gather(
        *[to_thread(_opine, e, n, lens, context) for e, n, lens in PERSONAS],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, str) and r]
