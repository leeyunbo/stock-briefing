"""부동산 브리핑 — 시스템 프롬프트, 프롬프트 빌더, AI 호출."""

import logging
from datetime import date

from app.collector.real_estate import RealEstateData
from app.pipeline.base import BriefingResult
from app.summarizer import SEO_INSTRUCTION, WRITING_STYLE_RULES, extract_seo_metadata, strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


REAL_ESTATE_REPORT_PROMPT = """당신은 부동산 시장 코멘터리 에디터예요.
경제 유튜버 스타일로 부동산 뉴스와 청약 정보를 쉽고 재미있게 해설해요.
"여기 사세요"가 아니라 "이런 일이 일어나고 있어요"를 전달하는 게 핵심이에요.

톤앤매너:
- "~요" 체 사용 (교육적이고 친근한 톤)
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "분양가상한제(정부가 분양가 상한을 정하는 제도)")
- 투자 권유/추천 절대 금지. "이런 일이 일어나고 있어요" 톤 유지
- <strong> 태그로 핵심 강조
- 이모지는 섹션 제목에만 1개씩

작성 규칙:
- HTML 형식 (이메일 발송용)
- <h2> 태그 (인라인 스타일 넣지 마세요, 후처리에서 자동 적용)
- 비교 데이터는 <table> 활용 (청약 비교 시)
- <div>, <style>, CSS class, 인라인 style 속성 사용 금지
- 본문 맨 위에 날짜/제목 쓰지 마세요

섹션 구성:

1. 📰 오늘의 부동산 핵심 뉴스 (2~3개)
- 무슨 일이 있었는지 (팩트)
- 왜 중요한지 (해설)
- 시장에 미치는 영향

2. 🏠 이번 주 주목할 청약 (TOP 3~5개)
- 단지명, 위치, 세대수, 분양가
- 선정 이유 (입지, 가격 메리트, 대단지 등)
- 접수 일정
- 청약 정보는 <table>로 깔끔하게 정리

3. 📊 부동산 시장 온도 체크
- 전반적인 시장 분위기 한 줄 요약
- 뉴스와 청약을 종합한 트렌드 해석

면책 문구:
- 본문 마지막에 "본 콘텐츠는 정보 제공 목적이며, 투자 권유가 아닙니다." 포함

청약 데이터가 없으면 2번 섹션은 "이번 주 수도권 신규 청약 공고가 없어요"로 간단히 처리하세요.
뉴스 데이터가 없으면 1번 섹션은 건너뛰고 가용한 데이터로만 작성하세요.
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION


def _build_real_estate_prompt(data: RealEstateData) -> str:
    """뉴스 + 청약 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {data.scan_date}\n"]

    # 뉴스
    if data.news:
        parts.append("## 부동산 뉴스")
        for n in data.news:
            parts.append(f"- {n.title}")
            if n.summary:
                parts.append(f"  {n.summary[:200]}")
            parts.append(f"  링크: {n.link}")
    else:
        parts.append("## 부동산 뉴스\n- 수집된 뉴스 없음")

    # 청약 공고
    if data.subscriptions:
        parts.append("\n## 청약 공고 (수도권)")
        for sub in data.subscriptions:
            parts.append(f"\n### {sub.house_name} ({sub.status})")
            parts.append(f"- 위치: {sub.address}")
            parts.append(f"- 지역: {sub.area}")
            parts.append(f"- 유형: {sub.house_type}")
            parts.append(f"- 총 세대수: {sub.total_supply_count:,}세대")
            parts.append(f"- 접수 기간: {sub.receipt_start} ~ {sub.receipt_end}")
            parts.append(f"- 당첨자 발표: {sub.winner_announce}")
            if sub.detail_url:
                parts.append(f"- 상세: {sub.detail_url}")

            # 분양가 정보
            prices = data.prices.get(sub.house_manage_no, [])
            if prices:
                parts.append("- 분양가:")
                for p in prices:
                    area_pyeong = p.supply_area / 3.3058
                    parts.append(
                        f"  · {p.house_type_area} ({p.supply_area:.1f}m², "
                        f"약 {area_pyeong:.0f}평): "
                        f"{p.top_amount:,}만원 ({p.supply_count}세대)"
                    )
    else:
        parts.append("\n## 청약 공고\n- 이번 주 수도권 신규 청약 없음")

    return "\n".join(parts)


def generate_real_estate_report(data: RealEstateData, run_id: str = "") -> BriefingResult:
    """Claude에게 부동산 브리핑 리포트 생성을 요청한다."""
    prompt = _build_real_estate_prompt(data)
    provider = get_cli_provider(timeout=600, pipeline="real_estate", stage="generate_report", run_id=run_id)
    raw = provider.call(REAL_ESTATE_REPORT_PROMPT, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    title = seo.title or f"{date.today().strftime('%Y년 %m월 %d일')} 부동산 브리핑"
    logger.info("부동산 브리핑 리포트 생성 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword)
