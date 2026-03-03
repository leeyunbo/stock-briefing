"""개별 종목 딥리서치 — 시스템 프롬프트, 프롬프트 빌더, AI 호출."""

import logging
from datetime import date

from app.collector.research_models import StockResearchData
from app.pipeline.base import BriefingResult
from app.prompts import fmt_money, fmt_num, fmt_pct
from app.summarizer import SEO_INSTRUCTION, WRITING_STYLE_RULES, extract_seo_metadata, strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


RESEARCH_SYSTEM_PROMPT = """당신은 골드만삭스·모건스탠리급 셀사이드 애널리스트이자, 2030 직장인을 위한 주식 심화 분석 에디터예요.
뉴닉(Newneek) 스타일의 친근한 톤이지만, 내용은 증권사 리서치 센터에서 나오는 심층 보고서 수준이어야 해요.

핵심 원칙:
- **의견을 내세요.** 단순 데이터 나열이 아닌, 데이터를 근거로 한 명확한 투자 판단을 제시하세요.
- "이 숫자가 왜 중요한지", "이게 투자에 어떤 의미인지"를 반드시 설명하세요.
- 호재와 악재를 균형 있게 다루되, 최종적으로 자신의 관점을 밝히세요.
- "~할 수 있습니다", "~일 수도 있어요" 같은 애매한 표현을 최소화하고, "~라고 봅니다", "~가 핵심이에요" 같은 확신 있는 톤을 쓰세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "PER(주가수익비율, 낮을수록 저평가)")
- 숫자는 강조하되 맥락을 함께 제공 — "PER 25배"가 아니라 "PER 25배로 업종 평균(18배) 대비 38% 프리미엄"
- 중요한 부분은 <strong> 태그로 볼드 처리
- 이모지는 섹션 제목에만 1개씩
- 독자에게 말을 거는 듯한 톤

작성 규칙:
- HTML 형식 (이메일 발송용)
- 각 섹션은 <h2> 태그 (인라인 스타일 넣지 마세요, 후처리에서 자동 적용)
- 비교 데이터는 <table><tr><th><td> 태그로 테이블 활용 (peer 비교, 재무 트렌드 등)
- 핵심 지표는 <strong>으로 강조
- <h2>, <ul>, <li>, <strong>, <p>, <br>, <table>, <tr>, <th>, <td> 등 기본 태그만 사용
- <div>, <style>, CSS class, 인라인 style 속성 사용 금지
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요

섹션 구성 (반드시 이 순서대로):

1. 📊 투자 요약
- 한 줄 판단: 매수/관망/매도 + 이유 — 애매하게 쓰지 말고 확실한 의견
- 현재가, 목표주가, 상승여력
- 핵심 포인트 3개 (불릿)

2. 🏢 사업 분석
- 뭘 하는 회사인지 쉽게 설명
- 매출 구성 (있으면 테이블)
- 경쟁 우위(moat)가 뭔지 — "이 회사가 대체 왜 잘나가는지/못나가는지" 분석가 시각으로
- 동종업계 포지션 — peer 비교 테이블 (시총, PER, 마진 등)
- 💡 애널리스트 코멘트: 이 사업의 구조적 강점 또는 약점에 대한 의견

3. 💰 재무 분석
- 최근 4분기 실적 트렌드 (테이블 권장: 매출, 영업이익, 순이익)
- 마진 변화 흐름 — 개선/악화 추세에 대한 해석
- FCF(잉여현금흐름) 상황 — 돈을 실제로 벌고 있는지, 현금 소진 중인지
- 핵심 지표 peer 비교 테이블
- 💡 애널리스트 코멘트: 재무 건전성에 대한 판단 (예: "적자가 일시적인지 구조적인지", "마진 회복 가능성")

4. 📈 밸류에이션
- PER/PBR/PS 현재 수준 — 단순 수치가 아니라 "비싼지 싼지" 판단
- 52주 고저 대비 현재 위치
- Peer 대비 프리미엄/디스카운트 — 프리미엄이 정당화되는지 분석
- 목표주가 산출 근거 — 구체적인 멀티플 적용 로직 (예: "업종 평균 PER 20배 × 예상 EPS $5 = $100")

5. ⚡ 호재와 악재
- 🟢 호재: 주가에 긍정적인 최근 이벤트·뉴스 (구체적으로, 왜 호재인지 설명)
- 🔴 악재: 주가에 부정적인 최근 이벤트·뉴스 (구체적으로, 얼마나 심각한지 판단)
- 애널리스트 추천 추이 (강력매수/매수/중립/매도 비율)
- 💡 종합 판단: 호재와 악재 중 어느 쪽이 더 무거운지 의견

6. ⚠️ 리스크 요인
- 사업 리스크, 재무 리스크, 시장 리스크 각 1-2개
- 각 리스크가 현실화될 확률과 임팩트를 평가 (예: "발생 가능성 중간, 임팩트 높음")
- 구체적이고 현실적인 리스크만

7. 🎯 결론
- Bull 시나리오 (목표주가 상단) + 트리거 조건
- Base 시나리오 (목표주가) + 핵심 가정
- Bear 시나리오 (목표주가 하단) + 트리거 조건
- 최종 판단 2-3줄: "지금 사야 하는지, 기다려야 하는지, 팔아야 하는지" 명확하게

데이터가 없는 항목은 "데이터 미확보"로 표시하되, 가능한 범위에서 분석을 계속하세요.
숫자를 표시할 때 큰 수는 읽기 쉽게 (예: $1,234.5B, $56.7M) 변환하세요.

⚠️ 데이터 신뢰도 주의:
- 제공된 EPS/실적 데이터의 기간(period)이 오늘 날짜 기준으로 아직 도래하지 않았거나, 해당 기업의 회계연도·실적 발표 일정상 아직 발표되지 않았을 수 있습니다.
- 실적 beat/miss를 언급할 때는 반드시 해당 분기의 실적이 실제로 발표된 것인지 확인하세요. 확신할 수 없으면 "실적 발표 예정" 또는 "컨센서스 추정치"로 표현하세요.
- 데이터 소스의 날짜 매핑이 회사의 실제 회계연도와 다를 수 있으므로, 비표준 회계연도(예: 4월 결산) 기업은 특히 주의하세요.
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION


def _build_research_prompt(data: StockResearchData) -> str:
    """수집 데이터를 딥리서치 프롬프트로 변환한다."""
    parts = [f"## 오늘 날짜: {date.today().isoformat()}\n## 종목: {data.ticker}\n"]

    if data.profile.name:
        p = data.profile
        cap_m = p.market_cap * 1_000_000
        parts.append("## 기업 프로필")
        parts.append(f"- 이름: {p.name}")
        parts.append(f"- 거래소: {p.exchange}, 산업: {p.industry}")
        parts.append(f"- 시가총액: {fmt_money(cap_m)}, IPO: {p.ipo}, 국가: {p.country}")

    if data.quote.current > 0:
        q = data.quote
        parts.append(f"\n## 현재 시세")
        parts.append(f"- 현재가: ${q.current:,.2f} ({q.change_pct:+.2f}%)")
        parts.append(f"- 고/저: ${q.high:,.2f} / ${q.low:,.2f}, 전일: ${q.prev_close:,.2f}")

    fin = data.financials
    if any(v is not None for v in [fin.pe_ttm, fin.pb_annual, fin.ps_ttm, fin.roe_ttm, fin.gross_margin_ttm]):
        parts.append(f"\n## 핵심 밸류에이션/재무지표")
        parts.append(f"- PER {fmt_num(fin.pe_ttm)}, PBR {fmt_num(fin.pb_annual)}, PSR {fmt_num(fin.ps_ttm)}")
        parts.append(f"- ROE {fmt_pct(fin.roe_ttm)}, ROI {fmt_pct(fin.roi_ttm)}")
        parts.append(f"- 매출총이익률 {fmt_pct(fin.gross_margin_ttm)}, 영업이익률 {fmt_pct(fin.operating_margin_ttm)}, 순이익률 {fmt_pct(fin.net_margin_ttm)}")
        parts.append(f"- 부채비율 {fmt_num(fin.debt_equity)}, 유동비율 {fmt_num(fin.current_ratio)}, 베타 {fmt_num(fin.beta)}")
        parts.append(f"- 52주 고가 ${fin.week52_high or 0:,.2f} ({fin.week52_high_date}), 저가 ${fin.week52_low or 0:,.2f} ({fin.week52_low_date})")
        parts.append(f"- 3년 매출성장 {fmt_pct(fin.revenue_growth_3y)}, 3년 EPS성장 {fmt_pct(fin.eps_growth_3y)}")

    if data.earnings:
        parts.append(f"\n## 최근 분기별 EPS")
        for e in data.earnings:
            beat = ""
            if e.surprise_pct is not None:
                beat = f" → {'Beat' if e.surprise_pct > 0 else 'Miss'} {e.surprise_pct:+.1f}%"
            actual = f"${e.actual:.2f}" if e.actual is not None else "N/A"
            estimate = f"${e.estimate:.2f}" if e.estimate is not None else "N/A"
            parts.append(f"- {e.period}: 실제 {actual} vs 예상 {estimate}{beat}")

    if data.recommendations:
        parts.append(f"\n## 애널리스트 추천 추이")
        for r in data.recommendations:
            total = r.strong_buy + r.buy + r.hold + r.sell + r.strong_sell
            parts.append(f"- {r.period}: 강력매수 {r.strong_buy}, 매수 {r.buy}, 중립 {r.hold}, 매도 {r.sell}, 강력매도 {r.strong_sell} (총 {total})")

    if data.news:
        parts.append(f"\n## 최근 7일 뉴스")
        for n in data.news:
            parts.append(f"- [{n.source}] {n.headline}")
            if n.summary:
                parts.append(f"  {n.summary[:200]}")

    annual_income = [r for r in data.income_statements if r.period_type == "annual"]
    quarterly_income = [r for r in data.income_statements if r.period_type == "quarterly"]

    if annual_income:
        parts.append(f"\n## 연간 손익계산서")
        for r in annual_income[:4]:
            parts.append(f"- {r.period}: 매출 {fmt_money(r.total_revenue)}, 영업이익 {fmt_money(r.operating_income)}, 순이익 {fmt_money(r.net_income)}, EBITDA {fmt_money(r.ebitda)}")

    if quarterly_income:
        parts.append(f"\n## 분기별 손익계산서")
        for r in quarterly_income[:4]:
            parts.append(f"- {r.period}: 매출 {fmt_money(r.total_revenue)}, 영업이익 {fmt_money(r.operating_income)}, 순이익 {fmt_money(r.net_income)}")

    annual_bs = [r for r in data.balance_sheets if r.period_type == "annual"]
    if annual_bs:
        parts.append(f"\n## 연간 대차대조표")
        for r in annual_bs[:4]:
            parts.append(f"- {r.period}: 자산 {fmt_money(r.total_assets)}, 부채 {fmt_money(r.total_liabilities)}, 자본 {fmt_money(r.stockholders_equity)}, 현금 {fmt_money(r.total_cash)}, 순부채 {fmt_money(r.net_debt)}")

    annual_cf = [r for r in data.cash_flows if r.period_type == "annual"]
    if annual_cf:
        parts.append(f"\n## 연간 현금흐름표")
        for r in annual_cf[:4]:
            parts.append(f"- {r.period}: 영업CF {fmt_money(r.operating_cf)}, Capex {fmt_money(r.capital_expenditure)}, FCF {fmt_money(r.free_cash_flow)}")

    if data.price_history:
        prices = data.price_history
        latest = prices[-1].close
        year_ago = prices[0].close
        year_return = ((latest - year_ago) / year_ago * 100) if year_ago else 0
        parts.append(f"\n## 1년 주가: {year_return:+.1f}% (${min(p.close for p in prices):,.2f} ~ ${max(p.close for p in prices):,.2f})")

    if data.sec_filings:
        parts.append(f"\n## 최근 SEC 공시")
        for filing in data.sec_filings:
            parts.append(f"- [{filing.form_type}] {filing.filing_date}: {filing.description}")

    if data.peer_financials:
        parts.append(f"\n## Peer 기업 비교")
        for pf in data.peer_financials:
            cap = fmt_money(pf.market_cap * 1_000_000) if pf.market_cap else "N/A"
            parts.append(f"- {pf.name} ({pf.ticker}): 시총 {cap}, PER {fmt_num(pf.pe_ttm)}, ROE {fmt_pct(pf.roe_ttm)}, 영업이익률 {fmt_pct(pf.operating_margin_ttm)}")

    return "\n".join(parts)


def summarize_research(data: StockResearchData, run_id: str = "", pipeline: str = "deep_research") -> BriefingResult:
    """딥 리서치 데이터로 개별 종목 보고서를 생성한다."""
    prompt = _build_research_prompt(data)
    provider = get_cli_provider(timeout=600, pipeline=pipeline, stage="summarize", run_id=run_id)
    raw = provider.call(RESEARCH_SYSTEM_PROMPT, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    name = data.profile.name or data.ticker
    title = seo.title or f"{name} ({data.ticker}) 심화 분석 리포트"
    logger.info("딥리서치 보고서 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword)
