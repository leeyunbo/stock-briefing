"""SEO 콘텐츠 패턴별 AI 프롬프트.

기존 summarizer.py의 WRITING_STYLE_RULES, SEO_INSTRUCTION, extract_seo_metadata를 재사용.
"""

from __future__ import annotations

import logging

from app.collector.kr_research_models import KRStockResearchData
from app.collector.research_models import StockResearchData
from app.pipeline.base import BriefingResult
from app.summarizer import (
    WRITING_STYLE_RULES,
    SEO_INSTRUCTION,
    extract_seo_metadata,
    get_provider,
    strip_code_block,
)

logger = logging.getLogger(__name__)

# ── 공통 베이스 ──

_BASE_TONE = """\
당신은 2030 직장인을 위한 투자 가이드 블로그 에디터예요.
뉴닉(Newneek) 스타일로 친근하고 쉽게 작성해주세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용
- 어려운 용어는 괄호로 쉽게 풀어주기
- 숫자는 강조하되 맥락을 함께
- 중요한 부분은 <strong> 태그로 볼드 처리
- 이모지는 섹션 제목에만 1개씩

작성 규칙:
- HTML 형식 (블로그 게시용)
- 각 섹션은 <h2> 태그
- 인라인 style 속성 금지
- 각 섹션당 5~10문장으로 깊이 있게 서술
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요
- <h2>, <h3>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용
"""

_STOCK_DATA_RULES = """
데이터 활용 규칙:
- 아래 제공된 데이터의 수치만 사용하세요
- 데이터에 없는 수치를 추측하거나 만들어내지 마세요
- 데이터가 부족한 부분은 "현재 확인 가능한 데이터가 제한적"이라고 표현하세요
"""

# ── 패턴별 시스템 프롬프트 ──

STOCK_DIVIDEND_SYSTEM = _BASE_TONE + _STOCK_DATA_RULES + """
주제: {keyword}의 배당금을 종합 정리하는 글을 작성하세요.

섹션 구성:
1. 💰 {keyword} 배당금 요약 — 최근 배당금, 배당수익률, 배당 성향
2. 📊 최근 5년 배당 이력 — 연도별 배당금 추이 (있으면 테이블, 없으면 문장형)
3. 📅 배당 기준일과 지급일 — 배당락일, 기준일, 지급 예정일
4. 🏢 동종업계 배당 비교 — 같은 섹터 주요 종목과 배당수익률 비교
5. 🔮 향후 배당 전망 — 실적 기반 배당 증감 전망
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

STOCK_TARGET_PRICE_SYSTEM = _BASE_TONE + _STOCK_DATA_RULES + """
주제: {keyword}의 목표주가와 투자 전망을 분석하는 글을 작성하세요.

섹션 구성:
1. 🎯 {keyword} 현재가 vs 목표주가 — 증권사 컨센서스, 괴리율
2. 📈 밸류에이션 분석 — PER, PBR, EPS 기반 적정가치 분석
3. 📊 차트 분석 — 지지선/저항선, 이동평균선, 추세
4. ✅ 투자 포인트 — 긍정적 요인 3~4가지
5. ⚠️ 리스크 요인 — 주의할 점 2~3가지
6. 🔮 종합 전망 — 투자 매력도 총정리
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

STOCK_EARNINGS_SYSTEM = _BASE_TONE + _STOCK_DATA_RULES + """
주제: {keyword}의 실적을 분석하는 글을 작성하세요.

섹션 구성:
1. 📊 {keyword} 최신 실적 요약 — 매출, 영업이익, 순이익 핵심 수치
2. 📈 실적 추이 — 최근 4~8분기 실적 변화 트렌드
3. 🔍 실적 분석 — 호실적/부진 원인, 사업부별 기여
4. 🏢 업종 내 비교 — 동종업계 실적 대비 포지셔닝
5. 🔮 향후 실적 전망 — 컨센서스, 성장 드라이버
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

STOCK_OUTLOOK_SYSTEM = _BASE_TONE + _STOCK_DATA_RULES + """
주제: {keyword}의 주가 전망을 분석하는 글을 작성하세요.

섹션 구성:
1. 📊 {keyword} 현재 상황 진단 — 최근 주가 흐름, 시장 포지션
2. ✅ 긍정 요인 — 성장 동력, 호재 3~4가지
3. ⚠️ 리스크 요인 — 불확실성, 악재 2~3가지
4. 🔍 수급 분석 — 기관/외인 동향, 공매도
5. 🔮 종합 전망 — 단기/중기/장기 시나리오
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

THEME_RELATED_SYSTEM = _BASE_TONE + """
주제: {keyword} 관련주를 소개하는 글을 작성하세요.

섹션 구성:
1. 🔍 {keyword} 테마 개요 — 왜 주목받는지, 시장 배경
2. 🏆 {keyword} 관련주 TOP 5~7 — 각 종목의 관련성, 핵심 사업
3. 📊 관련주 비교 분석 — 시가총액, PER, 성장성 비교
4. 💡 투자 전략 — 어떤 종목이 유망한지, 접근 방법
5. ⚠️ 유의사항 — 테마주 투자 리스크, 주의점
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

THEME_LEADER_SYSTEM = _BASE_TONE + """
주제: {keyword} 대장주를 분석하는 글을 작성하세요.

섹션 구성:
1. 🏆 {keyword} 대장주는? — 시장에서 대장주로 꼽히는 종목과 이유
2. 📊 대장주 핵심 지표 — 시가총액, 매출, 성장률
3. 🔍 경쟁사 비교 — 대장주 vs 2~3위 종목 비교
4. 📈 주가 흐름 — 최근 주가 추이, 테마 수혜 이력
5. 🔮 전망 — 대장주 유지 가능성, 투자 포인트
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

CONCEPT_DEFINITION_SYSTEM = _BASE_TONE + """
주제: {keyword}에 대해 쉽게 설명하는 글을 작성하세요. 투자 초보도 이해할 수 있도록.

섹션 구성:
1. 📚 {keyword}이란? — 한 줄 정의 + 쉬운 비유로 설명
2. 🔍 왜 중요한가요? — 투자에서 이 개념이 중요한 이유
3. 📊 실전 활용법 — 실제 투자할 때 어떻게 활용하는지 (예시 포함)
4. ⚠️ 흔한 오해와 주의점 — 초보자가 자주 실수하는 부분
5. 💡 정리 — 핵심 포인트 요약
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

CONCEPT_STRUCTURE_SYSTEM = _BASE_TONE + """
주제: {keyword}의 구조를 깊이 있게 분석하는 글을 작성하세요.

섹션 구성:
1. 🏗️ {keyword} 구조 개요 — 전체 구조를 한눈에
2. 🔍 핵심 구성요소 — 각 요소의 역할과 관계
3. 📊 실제 사례 — 구체적인 예시로 이해하기
4. ⚡ 장단점 — 이 구조의 장점과 한계
5. 💡 투자자가 알아야 할 포인트 — 실전 시사점
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

GSC_OPPORTUNITY_SYSTEM = _BASE_TONE + """
주제: "{keyword}"에 대해 검색 의도에 맞는 심층 콘텐츠를 작성하세요.

이 키워드는 Google Search Console에서 발견된 기회 키워드입니다.
사람들이 이 키워드를 검색할 때 원하는 정보를 최대한 충족시키는 글을 작성하세요.

가이드:
- 검색 의도를 파악하고, 그에 맞는 섹션 구성을 자유롭게 설계하세요
- 최소 4개 이상의 <h2> 섹션으로 구성
- 데이터와 수치를 포함해 신뢰감 있게
- 실전적이고 구체적인 정보 위주
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION

# ── 패턴 → 프롬프트 매핑 ──

_SYSTEM_PROMPTS: dict[str, str] = {
    "stock_dividend": STOCK_DIVIDEND_SYSTEM,
    "stock_target_price": STOCK_TARGET_PRICE_SYSTEM,
    "stock_earnings": STOCK_EARNINGS_SYSTEM,
    "stock_outlook": STOCK_OUTLOOK_SYSTEM,
    "theme_related": THEME_RELATED_SYSTEM,
    "theme_leader": THEME_LEADER_SYSTEM,
    "concept_definition": CONCEPT_DEFINITION_SYSTEM,
    "concept_structure": CONCEPT_STRUCTURE_SYSTEM,
    "gsc_opportunity": GSC_OPPORTUNITY_SYSTEM,
}


def build_seo_prompt(
    pattern_type: str,
    keyword: str,
    kr_data: KRStockResearchData | None = None,
    us_data: StockResearchData | None = None,
) -> tuple[str, str]:
    """패턴과 키워드로 시스템/유저 프롬프트를 생성한다.

    Returns:
        (system_prompt, user_prompt)
    """
    system_tmpl = _SYSTEM_PROMPTS.get(pattern_type, GSC_OPPORTUNITY_SYSTEM)
    system_prompt = system_tmpl.replace("{keyword}", keyword)

    # 유저 프롬프트 구성 — 실제 수집 데이터가 있으면 기존 빌더 재사용
    if kr_data is not None:
        from app.prompts.stock_deep_dive import _build_kr_prompt
        user_prompt = _build_kr_prompt(kr_data)
    elif us_data is not None:
        from app.prompts.deep_research import _build_research_prompt
        user_prompt = _build_research_prompt(us_data)
    else:
        # theme/concept 패턴 — 데이터 없이 키워드만
        user_prompt = (
            f"키워드: {keyword}\n\n"
            "위 키워드에 대해 SEO 최적화된 블로그 글을 작성해주세요. "
            "확인되지 않은 수치는 '확인 필요'라고 표시하세요."
        )

    return system_prompt, user_prompt


def generate_seo_article(
    pattern_type: str,
    keyword: str,
    kr_data: KRStockResearchData | None = None,
    us_data: StockResearchData | None = None,
    run_id: str = "",
) -> BriefingResult:
    """AI를 호출해 SEO 글을 생성한다.

    Returns:
        BriefingResult (title, html, slug, tags, focus_keyword 등).
    """
    system_prompt, user_prompt = build_seo_prompt(pattern_type, keyword, kr_data, us_data)

    provider = get_provider(pipeline="seo_content", stage="generate", run_id=run_id)
    raw = provider.call(system_prompt, user_prompt)
    raw = strip_code_block(raw)

    seo = extract_seo_metadata(raw)

    return BriefingResult(
        title=seo.title or f"{keyword} 투자 가이드",
        html=seo.html,
        slug=seo.slug,
        excerpt=seo.excerpt,
        tags=seo.tags,
        focus_keyword=seo.focus_keyword or keyword,
        image_keyword=seo.image_keyword,
    )
