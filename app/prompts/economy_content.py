"""경제 상식 콘텐츠 AI 프롬프트."""

from __future__ import annotations

import logging

from app.pipeline.base import BriefingResult
from app.summarizer import (
    SEO_INSTRUCTION,
    extract_seo_metadata,
    get_provider,
    strip_code_block,
)

logger = logging.getLogger(__name__)

_BASE_TONE = """\
당신은 경제/재테크를 처음 접하는 2030 직장인을 위한 경제 상식 블로그 에디터예요.
어려운 경제 용어를 누구나 이해할 수 있도록 쉽고 친근하게 설명해주세요.

톤앤매너:
- "~요" 체 사용, 친근하고 따뜻한 말투
- 전문 용어는 반드시 쉬운 말로 풀어서 설명
- 실생활 예시를 적극 활용 (월급, 대출, 전셋집 등)
- 숫자와 수치는 맥락과 함께 이해하기 쉽게
- 중요한 개념은 <strong> 태그로 강조
- 이모지는 섹션 제목에만 1개씩

작성 규칙:
- HTML 형식 (블로그 게시용)
- 각 섹션은 <h2> 태그
- 인라인 style 속성 금지
- 각 섹션당 5~8문장으로 충분히 설명
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요
- <h2>, <h3>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용

마지막 섹션으로 반드시 FAQ를 포함하세요:
- <h2>❓ 자주 묻는 질문</h2> 섹션을 본문 맨 끝(<!-- SEO --> 앞)에 추가
- 3~5개의 Q&A를 아래 형식으로 작성:
  <h3>Q. 질문 내용?</h3>
  <p>답변 내용</p>
- 실제 독자들이 궁금해할 만한 질문 위주로
- 답변은 2~3문장으로 간결하게
"""

_REALESTATE_SYSTEM = _BASE_TONE + """
부동산 개념 설명 글을 작성합니다.

섹션 구성:
1. 🏠 {keyword}가 뭔가요? — 핵심 개념을 아주 쉽게 정의
2. 💡 실생활에서 이렇게 쓰여요 — 구체적인 사례와 예시
3. ⚠️ 꼭 알아야 할 주의사항 — 실수하기 쉬운 포인트
4. 📋 이것만 기억하세요 — 핵심 요약 3가지
5. ❓ 자주 묻는 질문
"""

_CONCEPT_SYSTEM = _BASE_TONE + """
경제 개념/용어 설명 글을 작성합니다.

섹션 구성:
1. 📖 {keyword}가 뭔가요? — 핵심 개념을 아주 쉽게 정의
2. 🔍 왜 중요한가요? — 우리 일상/투자에 미치는 영향
3. 📊 실제 사례로 이해하기 — 숫자와 예시로 체감
4. 💬 이렇게 활용해요 — 실생활/투자에서의 응용
5. ❓ 자주 묻는 질문
"""

_INVEST_SYSTEM = _BASE_TONE + """
투자 개념/방법 설명 글을 작성합니다.

섹션 구성:
1. 💰 {keyword}가 뭔가요? — 핵심 개념 쉽게 정의
2. 📈 어떻게 활용하나요? — 실제 투자에서의 쓰임새
3. ✅ 장점과 ⚠️ 주의사항 — 균형 잡힌 시각 제공
4. 🔰 초보자도 따라할 수 있는 방법 — 실천 가이드
5. ❓ 자주 묻는 질문
"""

_SYSTEM_PROMPTS: dict[str, str] = {
    "economy_realestate": _REALESTATE_SYSTEM,
    "economy_concept": _CONCEPT_SYSTEM,
    "economy_invest": _INVEST_SYSTEM,
}


def generate_economy_article(
    pattern_type: str,
    keyword: str,
    run_id: str = "",
) -> BriefingResult:
    system_tmpl = _SYSTEM_PROMPTS.get(pattern_type, _CONCEPT_SYSTEM)
    system_prompt = system_tmpl.replace("{keyword}", keyword)

    user_prompt = (
        f"키워드: {keyword}\n\n"
        f"위 키워드에 대해 경제 초보자도 쉽게 이해할 수 있는 블로그 글을 작성해주세요.\n"
        f"실생활 예시를 풍부하게 활용하고, 전문 용어는 반드시 쉽게 풀어주세요.\n\n"
        + SEO_INSTRUCTION
    )

    provider = get_provider(pipeline="economy_content", stage="generate", run_id=run_id)
    raw = provider.call(system_prompt, user_prompt)
    raw = strip_code_block(raw)

    seo = extract_seo_metadata(raw)

    if not seo.title:
        seo.title = f"{keyword} 쉽게 이해하기"

    return BriefingResult(
        title=seo.title,
        html=seo.html,
        slug=seo.slug,
        excerpt=seo.excerpt,
        tags=seo.tags,
        focus_keyword=seo.focus_keyword or keyword,
        image_keyword=keyword,
    )
