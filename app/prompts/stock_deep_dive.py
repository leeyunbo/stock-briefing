"""종목 딥다이브 — 프롬프트 + 빌더 + AI 호출."""

import json
import logging
from datetime import date

from app.collector.kr_research_models import KRStockResearchData
from app.collector.research_models import StockResearchData
from app.pipeline.base import BriefingResult
from app.prompts import fmt_money, fmt_num, fmt_pct
from app.prompts.deep_research import RESEARCH_SYSTEM_PROMPT, _build_research_prompt
from app.summarizer import extract_seo_metadata, strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


# ── LLM #1: 자동 종목 선정 프롬프트 ──


PICK_STOCK_SYSTEM = """당신은 시장 분석 전문가예요. 오늘의 시장 데이터를 보고 딥다이브 분석할 종목 1개를 선정해주세요.

선정 기준:
1. 오늘 큰 등락이 있거나, 실적 발표가 있거나, 뉴스에서 주목받는 종목
2. 투자자 관심이 높은 종목 (거래량 급증, 시장 뉴스 빈도)
3. KR/US 모두 후보 가능 — 더 분석 가치가 높은 쪽 선정
4. 이전에 다룬 종목보다 새로운 종목 우선

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
    "ticker": "NVDA 또는 005930 또는 삼성전자",
    "market": "US 또는 KR",
    "why_picked": "선정 이유 한 줄"
}
"""


def pick_stock_prompt(scan_text: str, macro_text: str, kr_market_text: str, recent_titles: list[str] | None = None) -> str:
    """자동 모드 종목 선정용 프롬프트를 빌드한다."""
    parts = [
        f"## 오늘 날짜: {date.today().isoformat()}\n",
        "## US 시장 스캔 데이터\n",
        scan_text,
        "\n## 매크로 지표\n",
        macro_text,
        "\n## KR 시장 데이터\n",
        kr_market_text,
    ]
    if recent_titles:
        parts.append("\n## 최근 7일 이내 발행된 종목 (반드시 제외)\n" + "\n".join(f"- {t}" for t in recent_titles))
    parts.append("\n위 데이터를 종합해서 오늘 딥다이브 분석할 종목 1개를 선정해주세요.")
    return "\n".join(parts)


def call_pick_stock(scan_text: str, macro_text: str, kr_market_text: str, recent_titles: list[str] | None = None, run_id: str = "") -> dict:
    """LLM #1: 자동 종목 선정."""
    prompt = pick_stock_prompt(scan_text, macro_text, kr_market_text, recent_titles)
    provider = get_cli_provider(
        timeout=120, pipeline="stock_deep_dive", stage="pick_stock", run_id=run_id,
    )
    raw = provider.call(PICK_STOCK_SYSTEM, prompt)
    raw = strip_code_block(raw).strip()

    try:
        result = json.loads(raw)
        return {
            "ticker": result.get("ticker", ""),
            "market": result.get("market", "US"),
            "why_picked": result.get("why_picked", ""),
        }
    except json.JSONDecodeError:
        logger.error("종목 선정 JSON 파싱 실패: %s", raw[:200])
        return {"ticker": "NVDA", "market": "US", "why_picked": "파싱 실패 — 기본값"}


# ── LLM #2: KR 종목 프롬프트 빌더 ──


def _build_kr_prompt(data: KRStockResearchData) -> str:
    """KR 수집 데이터를 딥리서치 프롬프트로 변환한다."""
    parts = [f"## 오늘 날짜: {date.today().isoformat()}\n## 종목: {data.profile.name or data.ticker} ({data.code})\n"]

    if data.profile.name:
        p = data.profile
        parts.append("## 기업 프로필")
        parts.append(f"- 이름: {p.name}")
        parts.append(f"- 시장: {p.market}, 업종: {p.industry}")
        parts.append(f"- 시가총액: {p.market_cap:,}억 원")
        if p.per is not None:
            parts.append(f"- PER: {fmt_num(p.per)}")
        if p.pbr is not None:
            parts.append(f"- PBR: {fmt_num(p.pbr)}")
        if p.dividend_yield is not None:
            parts.append(f"- 배당수익률: {fmt_pct(p.dividend_yield)}")

    if data.quote.current > 0:
        q = data.quote
        parts.append(f"\n## 현재 시세")
        parts.append(f"- 현재가: {q.current:,}원 ({q.change_pct:+.2f}%)")
        parts.append(f"- 고/저: {q.high:,}원 / {q.low:,}원, 전일: {q.prev_close:,}원")
        parts.append(f"- 거래량: {q.volume:,}")

    annual = [r for r in data.financials if r.period_type == "annual"]
    quarterly = [r for r in data.financials if r.period_type == "quarterly"]

    if annual:
        parts.append(f"\n## 연간 재무제표")
        for r in annual[:5]:
            parts.append(
                f"- {r.period}: 매출 {_kr_money(r.revenue)}, "
                f"영업이익 {_kr_money(r.operating_income)}, "
                f"순이익 {_kr_money(r.net_income)}, "
                f"EPS {fmt_num(r.eps)}, ROE {fmt_pct(r.roe)}, "
                f"부채비율 {fmt_pct(r.debt_ratio)}"
            )

    if quarterly:
        parts.append(f"\n## 분기별 재무제표")
        for r in quarterly[:6]:
            parts.append(
                f"- {r.period}: 매출 {_kr_money(r.revenue)}, "
                f"영업이익 {_kr_money(r.operating_income)}, "
                f"순이익 {_kr_money(r.net_income)}"
            )

    if data.price_history:
        prices = data.price_history
        latest = prices[-1].close
        year_ago = prices[0].close
        year_return = ((latest - year_ago) / year_ago * 100) if year_ago else 0
        parts.append(
            f"\n## 1년 주가: {year_return:+.1f}% "
            f"({min(p.close for p in prices):,.0f}원 ~ {max(p.close for p in prices):,.0f}원)"
        )

    if data.news_headlines:
        parts.append(f"\n## 최근 뉴스")
        for headline in data.news_headlines[:10]:
            parts.append(f"- {headline}")

    return "\n".join(parts)


def generate_stock_article_kr(data: KRStockResearchData, run_id: str = "") -> BriefingResult:
    """KR 종목 딥리서치 기사를 생성한다."""
    prompt = _build_kr_prompt(data)
    provider = get_cli_provider(
        timeout=600, pipeline="stock_deep_dive", stage="generate_article", run_id=run_id,
    )
    raw = provider.call(RESEARCH_SYSTEM_PROMPT, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    name = data.profile.name or data.ticker
    title = seo.title or f"{name} ({data.code}) 심화 분석 리포트"
    return BriefingResult(
        title=title, html=seo.html, slug=seo.slug,
        excerpt=seo.excerpt, tags=seo.tags,
        focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword,
    )


def generate_stock_article_us(data: StockResearchData, run_id: str = "") -> BriefingResult:
    """US 종목 딥리서치 기사를 생성한다 (기존 deep_research 재사용)."""
    from app.prompts.deep_research import summarize_research
    return summarize_research(data, run_id=run_id, pipeline="stock_deep_dive")


# ── 유틸 ──


def _kr_money(value: float | None) -> str:
    """한국 금액을 읽기 쉽게 변환 (억 원 단위)."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 10000:
        return f"{sign}{abs_val / 10000:,.1f}조 원"
    return f"{sign}{abs_val:,.0f}억 원"
