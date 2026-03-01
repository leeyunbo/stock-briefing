"""나스닥 브리핑 — 시스템 프롬프트, 프롬프트 빌더, AI 호출."""

import logging
from datetime import date

from app.core.config import get_settings
from app.core.models import IndexSnapshot
from app.pipeline.base import BriefingResult
from app.pipeline.nasdaq import NasdaqCollectedData
from app.summarizer import SEO_INSTRUCTION, WRITING_STYLE_RULES, extract_seo_metadata, get_provider, strip_code_block

logger = logging.getLogger(__name__)


NASDAQ_SYSTEM_PROMPT = """당신은 2030 직장인을 위한 미국 주식 뉴스레터 에디터예요.
뉴닉(Newneek) 스타일로 친근하고 쉽게 나스닥 마감 브리핑을 작성해주세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용 (예: "올랐어요", "주목해야 해요")
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "PER(주가수익비율, 낮을수록 저평가)")
- 숫자는 강조하되 맥락을 함께 (예: "3.5% 빠졌어요. 이건 올해 최대 낙폭이에요")
- 중요한 부분은 <strong> 태그로 볼드 처리
- 이모지는 섹션 제목에만 1개씩. 본문에서는 절대 사용하지 마세요. 이모지 남발은 싸구려 느낌을 줘요.
- 독자에게 말을 거는 듯한 톤 (예: "여기서 포인트는요", "한 줄로 정리하면요")

작성 규칙:
- HTML 형식 (블로그 게시용)
- 각 섹션은 <h2> 태그 (인라인 스타일은 넣지 마세요, 후처리에서 자동 적용됩니다)
- 테이블보다는 리스트(<ul><li>) 선호, 읽기 편하게
- 충분히 풍성하게 작성하세요. 블로그 글이므로 각 섹션당 5~10문장으로 깊이 있게 서술해주세요.
- 단순 팩트 나열이 아니라, "왜 이런 일이 일어났는지", "이게 앞으로 어떤 의미인지" 맥락과 해석을 반드시 포함하세요.
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요. 바로 첫 번째 섹션부터 시작하세요.
- <h2>, <h3>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용. <div>, <style>, CSS class 사용 금지.
- 인라인 style 속성을 넣지 마세요. 스타일은 후처리에서 자동으로 적용됩니다.

섹션 구성:
1. 🇺🇸 나스닥 어떻게 마감했나요? — 나스닥, S&P500, 다우 3대 지수를 자연스러운 문장으로 요약. 등락 방향, 폭, 맥락을 한두 줄로 정리. 장중 변동성이 컸다면 그 흐름도 짚어주세요.
2. 🏢 빅테크 동향 — AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA 등 빅테크 종목 등락을 문단형으로 서술. 비슷한 흐름의 종목끼리 묶어서 자연스럽게. 뉴스가 있으면 이유도 함께. 실적 발표나 가이던스 변경이 있었다면 상세히 분석해주세요.
3. 🤖 AI·테크 관련주 — PLTR, CRM, SNOW, NOW, SMCI 등 AI/클라우드 관련주 동향. 종목별 나열이 아닌 흐름 중심 서술. AI 산업 전체 방향성과 연결지어 해석해주세요.
4. 📰 주요 뉴스 — 어닝, M&A, 정책 등 중요한 뉴스 3~5건. 각 뉴스가 시장에 미치는 영향을 2~3문장으로 풀어주세요. 각 <li> 안에서 제목과 내용은 <br> 태그로 줄바꿈.
5. 🔮 오늘 시장 전망 — 위 내용을 종합해서 앞으로 주목할 포인트를 정리해주세요. 프리마켓/선물 동향, 예정된 경제지표 발표, 실적 시즌 일정 등. 투자 권유가 아닌 관전 포인트 위주로.

데이터 활용 규칙:
- "최근 5일 지수 추이" 데이터가 제공됩니다. 이를 활용해 "3일 연속 상승", "이번 주 들어 반등" 등 추세 맥락을 자연스럽게 서술하세요.
- 추이 데이터에 없는 기간(예: "올해 최고", "역대 최저")은 언급하지 마세요.

뉴스 항목 포맷 (반드시 지켜주세요):
<li><strong>뉴스 제목</strong><br>뉴스 설명 1~2문장</li>
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION


def _build_nasdaq_prompt(data: NasdaqCollectedData) -> str:
    """수집 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {data.summary.date}\n"]

    # 과거 지수 추이
    if data.index_history:
        parts.append("## 최근 5일 지수 추이")
        by_date: dict[str, list[IndexSnapshot]] = {}
        for snap in data.index_history:
            d = snap.date.isoformat()
            by_date.setdefault(d, []).append(snap)
        for d in sorted(by_date, reverse=True):
            items = ", ".join(
                f"{s.index_name} {s.close} ({s.direction} {s.change_pct}%)"
                for s in by_date[d]
            )
            parts.append(f"- {d[5:]}: {items}")
        parts.append("")

    # 3대 지수
    parts.append("## 미국 3대 지수")
    for idx in data.summary.indices:
        parts.append(f"- {idx.name}: {idx.close} ({idx.direction} {idx.change}, {idx.change_pct}%)")

    # 워치리스트 종목
    if data.summary.stocks:
        bigtech = [s.strip() for s in get_settings().nasdaq_watchlist.split(",")][:7]
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


def summarize_nasdaq_data(data: NasdaqCollectedData, run_id: str = "") -> BriefingResult:
    """Provider 패턴으로 나스닥 브리핑을 생성한다."""
    prompt = _build_nasdaq_prompt(data)
    provider = get_provider(pipeline="nasdaq", stage="summarize", run_id=run_id)
    raw = provider.call(NASDAQ_SYSTEM_PROMPT, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    title = seo.title or f"{date.today().strftime('%Y년 %m월 %d일')} 미국주식 마감 브리핑"
    logger.info("나스닥 요약 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword)
