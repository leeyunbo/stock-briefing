"""나스닥 브리핑 파이프라인 — 기존 pipeline.py와 동일한 4단계 구조.

summarize 단계는 summarizer.py의 Provider 패턴을 재사용한다.
AI_PROVIDER=claude-cli 설정 시 claude -p CLI로, 그 외에는 API로 동작.
"""

import logging
from dataclasses import dataclass
from datetime import date

from app.collector.nasdaq import NasdaqSummary, fetch_nasdaq_summary
from app.pipeline import BriefingResult, save_briefing, send_emails
from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)


# ── 시스템 프롬프트 ──


NASDAQ_SYSTEM_PROMPT = """당신은 2030 직장인을 위한 미국 주식 뉴스레터 에디터예요.
뉴닉(Newneek) 스타일로 친근하고 쉽게 나스닥 마감 브리핑을 작성해주세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용 (예: "올랐어요", "주목해야 해요")
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "PER(주가수익비율, 낮을수록 저평가)")
- 숫자는 강조하되 맥락을 함께 (예: "3.5% 빠졌어요. 이건 올해 최대 낙폭이에요")
- 중요한 부분은 <strong> 태그로 볼드 처리
- 이모지는 섹션 제목에만 1개씩. 본문에서는 절대 사용하지 마세요.
- 독자에게 말을 거는 듯한 톤 (예: "여기서 포인트는요", "한 줄로 정리하면요")

작성 규칙:
- HTML 형식 (이메일 발송용)
- 각 섹션은 <h2> 태그 (인라인 스타일은 넣지 마세요, 후처리에서 자동 적용됩니다)
- 테이블보다는 리스트(<ul><li>) 선호, 읽기 편하게
- 핵심만 간결하게, 한 섹션당 3~5문장 이내
- "왜 중요한지" 맥락을 반드시 포함
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요. 이메일 헤더에 이미 있어요. 바로 첫 번째 섹션부터 시작하세요.
- <h2>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용. <div>, <style>, CSS class 사용 금지.
- 인라인 style 속성을 넣지 마세요. 스타일은 후처리에서 자동으로 적용됩니다.

섹션 구성:
1. 🇺🇸 나스닥 어떻게 마감했나요? — 나스닥, S&P500, 다우 3대 지수를 자연스러운 문장으로 요약. 등락 방향, 폭, 맥락을 한두 줄로 정리.
2. 🏢 빅테크 동향 — AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA 등 빅테크 종목 등락을 문단형으로 서술. 비슷한 흐름의 종목끼리 묶어서 자연스럽게. 뉴스가 있으면 이유도 함께.
3. 🤖 AI·테크 관련주 — PLTR, CRM, SNOW, NOW, SMCI 등 AI/클라우드 관련주 동향. 종목별 나열이 아닌 흐름 중심 서술.
4. 📰 주요 뉴스 — 어닝, M&A, 정책 등 중요한 뉴스 3~5건. 각 <li> 안에서 제목과 내용은 <br> 태그로 줄바꿈.

뉴스 항목 포맷 (반드시 지켜주세요):
<li><strong>뉴스 제목</strong><br>뉴스 설명 1~2문장</li>
"""


# ── 수집 데이터 ──


@dataclass
class NasdaqCollectedData:
    """나스닥 수집 단계 결과물."""

    summary: NasdaqSummary


# ── 파이프라인 단계 ──


async def collect_nasdaq() -> NasdaqCollectedData:
    """1단계: 나스닥 데이터를 수집한다."""
    try:
        summary = await fetch_nasdaq_summary()
    except Exception as e:
        logger.error("나스닥 데이터 수집 실패: %s", e)
        summary = NasdaqSummary()

    logger.info(
        "나스닥 수집 완료: 지수 %d개, 종목 %d개",
        len(summary.indices), len(summary.stocks),
    )
    return NasdaqCollectedData(summary=summary)


def _build_nasdaq_prompt(data: NasdaqCollectedData) -> str:
    """수집 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {data.summary.date}\n"]

    # 3대 지수
    parts.append("## 미국 3대 지수")
    for idx in data.summary.indices:
        parts.append(f"- {idx.name}: {idx.close} ({idx.direction} {idx.change}, {idx.change_pct}%)")

    # 워치리스트 종목
    if data.summary.stocks:
        # 빅테크
        bigtech = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA"]
        bigtech_stocks = [s for s in data.summary.stocks if s.ticker in bigtech]
        others = [s for s in data.summary.stocks if s.ticker not in bigtech]

        if bigtech_stocks:
            parts.append("\n## 빅테크 종목")
            for s in bigtech_stocks:
                parts.append(f"- {s.name} ({s.ticker}): ${s.close} ({s.direction} {s.change_pct}%) 시총 {s.market_cap}")
                for news in s.news:
                    parts.append(f"  · 뉴스: {news}")

        if others:
            parts.append("\n## AI·테크 관련주")
            for s in others:
                parts.append(f"- {s.name} ({s.ticker}): ${s.close} ({s.direction} {s.change_pct}%) 시총 {s.market_cap}")
                for news in s.news:
                    parts.append(f"  · 뉴스: {news}")

    return "\n".join(parts)


def summarize_nasdaq(data: NasdaqCollectedData) -> BriefingResult:
    """2단계: Provider 패턴으로 브리핑을 생성한다. config의 AI_PROVIDER 설정을 따른다."""
    prompt = _build_nasdaq_prompt(data)
    provider = get_provider()
    raw = provider.call(NASDAQ_SYSTEM_PROMPT, prompt)
    html = strip_code_block(raw)

    title = f"{date.today().strftime('%Y년 %m월 %d일')} 나스닥 마감 브리핑"
    logger.info("나스닥 요약 완료: %s", title)
    return BriefingResult(title=title, html=html)


# ── 오케스트레이터 ──


async def run_nasdaq_pipeline() -> str:
    """전체 나스닥 파이프라인: 수집 → 요약 → 저장 → 발송."""
    logger.info("나스닥 브리핑 파이프라인 시작: %s", date.today())

    data = await collect_nasdaq()
    result = summarize_nasdaq(data)
    await save_briefing(result, briefing_type="nasdaq")
    await send_emails(result)

    return result.html
