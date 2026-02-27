"""주식 리서치 파이프라인 — 두 가지 모드.

Mode A (기본): 뉴스 딥다이브 — 시장 코멘터리
  Stage 1 — 데이터 수집 (뉴스/시세 + 매크로 지표 병렬)
  Stage 2 — 뉴스 분석 → 핵심 이슈 + 관련/수혜 종목 (Claude #1)
  Stage 3 — 종목 데이터 보강 (재무지표 스크리닝)
  Stage 4 — 최종 리포트 생성 (Claude #2)

Mode B (--ticker): 개별 종목 딥리서치
  기존 단일 종목 심화 분석 보고서
"""

import json
import logging
import re
from datetime import date

import asyncio

from app.collector.stock_research import (
    CandidateScreenData,
    MacroIndicators,
    MarketScanData,
    StockResearchData,
    fetch_macro_indicators,
    fetch_stock_research,
    scan_market,
    screen_candidates,
)
from app.pipeline.base import BriefingResult, save_briefing, send_emails
from app.publishing.og_image import CATEGORY_DISPLAY, generate_og_image
from app.publishing.wordpress import publish_to_wordpress
from app.summarizer import SEO_INSTRUCTION, ClaudeCliProvider, extract_seo_metadata, strip_code_block

logger = logging.getLogger(__name__)


# ── 이메일 발송 헬퍼 (두 모드 공통) ──


async def _deliver(result: BriefingResult, briefing_type: str, email_to: list[str] | None) -> None:
    """결과를 DB에 저장하고, WordPress에 발행하고, 이메일을 발송한다."""
    await save_briefing(result, briefing_type=briefing_type)

    # OG 이미지 생성
    category = CATEGORY_DISPLAY.get(briefing_type, "뉴스 딥다이브")
    og_image = generate_og_image(result.title, category)

    # WordPress 자동 발행
    await publish_to_wordpress(
        result.title, result.html, briefing_type,
        slug=result.slug, excerpt=result.excerpt, tags=result.tags,
        og_image=og_image,
    )

    if email_to is not None:
        if email_to:
            from app.publishing.email_sender import send_briefing_to_subscribers
            from app.publishing.email_template import render_email
            email_html = render_email(result.title, result.html)
            send_result = await send_briefing_to_subscribers(email_to, result.title, email_html)
            logger.info("이메일 발송: 성공 %d, 실패 %d", send_result["success"], send_result["fail"])
    else:
        await send_emails(result)


# ══════════════════════════════════════════════
# Mode A: 뉴스 딥다이브 — 시장 코멘터리
# ══════════════════════════════════════════════


# ── Stage 2: 뉴스 분석 (Claude #1) ──


NEWS_ANALYSIS_PROMPT = """당신은 글로벌 매크로 전략가이자 경제 유튜버의 리서처예요.

아래 데이터(뉴스, 시세, 매크로 지표)를 분석해서:
1. 오늘 가장 중요한 뉴스/이슈 2~3개를 선정하세요
2. 각 이슈가 왜 중요한지, 어떤 종목이 영향받는지 분석하세요

이슈 선정 기준:
- 시장을 실제로 움직인 뉴스 (등락 TOP과 연결)
- 정책 변화, 실적 서프라이즈, 산업 구조 변화
- "왜 이런 일이 일어나고 있는지" 설명할 수 있는 이슈

종목 분석 기준:
- affected_tickers: 이 이슈로 직접 영향받는 종목 (상승이든 하락이든)
- beneficiary_tickers: 숨은 수혜주 (밸류체인, 부품, 대체재, 인프라)
  → 이게 핵심! 나스닥 100 밖 종목도 괜찮아요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "stories": [
    {
      "headline": "이슈 제목 (한국어)",
      "what_happened": "무슨 일이 있었는지 2~3문장",
      "why_it_matters": "왜 중요한지. 시장/경제에 미치는 영향 2~3문장",
      "affected_tickers": ["NVDA", "AMD", "TSMC"],
      "beneficiary_tickers": ["CEG", "VST", "ETN"]
    }
  ]
}
"""


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000_000:,.1f}T"
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:,.1f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:,.1f}M"
    return f"{sign}${abs_val:,.0f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}%"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _build_news_analysis_prompt(scan: MarketScanData, macro: MacroIndicators) -> str:
    """스캔 + 매크로 데이터를 뉴스 분석 프롬프트로 변환한다."""
    parts = [f"## 스캔 일자: {scan.scan_date}\n"]

    # 매크로 지표
    parts.append("## 매크로 지표")
    if macro.vix is not None:
        parts.append(f"- VIX: {macro.vix} ({macro.vix_change:+.2f})" if macro.vix_change is not None else f"- VIX: {macro.vix}")
    if macro.treasury_10y is not None:
        parts.append(f"- 10Y 국채금리: {macro.treasury_10y}% ({macro.treasury_10y_change:+.2f}%p)" if macro.treasury_10y_change is not None else f"- 10Y 국채금리: {macro.treasury_10y}%")
    if macro.dxy is not None:
        parts.append(f"- 달러인덱스(DXY): {macro.dxy} ({macro.dxy_change:+.2f})" if macro.dxy_change is not None else f"- 달러인덱스(DXY): {macro.dxy}")
    if macro.fear_greed_value is not None:
        parts.append(f"- Fear & Greed: {macro.fear_greed_value} ({macro.fear_greed_label})")
    if macro.sp500_close is not None:
        parts.append(f"- S&P 500: {macro.sp500_close:,.2f} ({macro.sp500_change_pct:+.2f}%)" if macro.sp500_change_pct is not None else f"- S&P 500: {macro.sp500_close:,.2f}")
    if macro.nasdaq_close is not None:
        parts.append(f"- 나스닥: {macro.nasdaq_close:,.2f} ({macro.nasdaq_change_pct:+.2f}%)" if macro.nasdaq_change_pct is not None else f"- 나스닥: {macro.nasdaq_close:,.2f}")
    if macro.dow_close is not None:
        parts.append(f"- 다우: {macro.dow_close:,.2f} ({macro.dow_change_pct:+.2f}%)" if macro.dow_change_pct is not None else f"- 다우: {macro.dow_close:,.2f}")
    if macro.gold_close is not None:
        parts.append(f"- 금: ${macro.gold_close:,.2f} ({macro.gold_change_pct:+.2f}%)" if macro.gold_change_pct is not None else f"- 금: ${macro.gold_close:,.2f}")
    if macro.wti_close is not None:
        parts.append(f"- WTI 유가: ${macro.wti_close:,.2f} ({macro.wti_change_pct:+.2f}%)" if macro.wti_change_pct is not None else f"- WTI 유가: ${macro.wti_close:,.2f}")

    if scan.top_gainers:
        parts.append("\n## 오늘 상승률 TOP 10")
        for s in scan.top_gainers:
            vol_ratio = f", 거래량 {s.volume / s.avg_volume:.1f}x" if s.avg_volume > 0 else ""
            parts.append(f"- {s.ticker}: {s.close:,.2f} ({s.change_pct:+.2f}%{vol_ratio})")

    if scan.top_losers:
        parts.append("\n## 오늘 하락률 TOP 10")
        for s in scan.top_losers:
            vol_ratio = f", 거래량 {s.volume / s.avg_volume:.1f}x" if s.avg_volume > 0 else ""
            parts.append(f"- {s.ticker}: {s.close:,.2f} ({s.change_pct:+.2f}%{vol_ratio})")

    if scan.top_volume:
        parts.append("\n## 거래량 급증 TOP 10 (평균 대비)")
        for s in scan.top_volume:
            ratio = s.volume / s.avg_volume if s.avg_volume > 0 else 0
            parts.append(f"- {s.ticker}: {ratio:.1f}x ({s.change_pct:+.2f}%)")

    if scan.earnings_today:
        parts.append("\n## 오늘 실적 발표 예정")
        for e in scan.earnings_today:
            eps = f", EPS 예상 ${e.eps_estimate:.2f}" if e.eps_estimate else ""
            parts.append(f"- {e.ticker}{eps}")

    if scan.earnings_tomorrow:
        parts.append("\n## 내일 실적 발표 예정")
        for e in scan.earnings_tomorrow:
            eps = f", EPS 예상 ${e.eps_estimate:.2f}" if e.eps_estimate else ""
            parts.append(f"- {e.ticker}{eps}")

    if scan.market_news:
        parts.append("\n## 시장 주요 뉴스 (최근 20건)")
        for n in scan.market_news:
            related = f" [{n.related}]" if n.related else ""
            parts.append(f"- {n.headline}{related}")
            if n.summary:
                parts.append(f"  {n.summary[:200]}")

    return "\n".join(parts)


def analyze_news(scan: MarketScanData, macro: MacroIndicators) -> dict:
    """Stage 2: Claude에게 뉴스+매크로를 주고 핵심 이슈 + 관련 종목을 도출한다."""
    prompt = _build_news_analysis_prompt(scan, macro)
    provider = ClaudeCliProvider(timeout=180)
    raw = provider.call(NEWS_ANALYSIS_PROMPT, prompt)
    raw = strip_code_block(raw.strip())

    json_match = re.search(r'\{[\s\S]+\}', raw)
    if json_match:
        raw = json_match.group()

    try:
        result = json.loads(raw)
        if "stories" not in result:
            raise ValueError("stories 키 없음")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("뉴스 분석 JSON 파싱 실패: %s / raw=%s", e, raw[:300])
        raise RuntimeError(f"Claude 뉴스 분석 실패: {raw[:300]}") from e


def _extract_mentioned_tickers(analysis: dict) -> list[str]:
    """뉴스 분석 결과에서 중복 없이 티커를 추출한다."""
    tickers = []
    seen = set()
    for story in analysis.get("stories", []):
        for key in ["affected_tickers", "beneficiary_tickers"]:
            for t in story.get(key, []):
                t = t.upper().strip()
                if t and t not in seen:
                    tickers.append(t)
                    seen.add(t)
    return tickers


# ── Stage 4: 뉴스 딥다이브 리포트 (Claude #2) ──


NEWS_DIVE_REPORT_PROMPT = """당신은 경제 유튜버 스타일의 시장 코멘터리 에디터예요.
"이걸 사세요"가 아니라 "이런 일이 일어나고 있어요"를 전달하는 게 핵심이에요.

아래 데이터를 분석해서 뉴스 딥다이브 리포트를 작성해주세요:
- 뉴스 분석 결과 (핵심 이슈 + 관련 종목)
- 각 종목의 실제 재무지표
- 매크로 지표 (VIX, 금리, 달러, Fear & Greed 등)

톤앤매너:
- "~요" 체 사용 (교육적이고 친근한 톤)
- 어려운 용어는 괄호로 쉽게 풀어주기
- 투자 권유/추천 절대 금지. "이런 일이 일어나고 있어요" 톤 유지
- <strong> 태그로 핵심 강조
- 이모지는 섹션 제목에만 1개씩

종목 표기 규칙:
- 반드시 "NVDA (엔비디아)" 형식 (티커 + 한국어 회사명)
- 처음 언급할 때만 풀네임, 이후는 티커만 사용 가능

작성 규칙:
- HTML 형식 (이메일 발송용)
- <h2> 태그 (인라인 스타일 넣지 마세요, 후처리에서 자동 적용)
- 비교 데이터는 <table> 활용
- <div>, <style>, CSS class, 인라인 style 속성 사용 금지
- 본문 맨 위에 날짜/제목 쓰지 마세요

섹션 구성:

1. 📌 오늘의 핵심 이슈 (2~3개)
- 이슈별로:
  · 무슨 일이 있었는지 (팩트)
  · 왜 중요한지 (해설)
  · 직접 영향받는 종목 + 현재 주가/등락
  · 숨은 수혜주 (밸류체인, 부품, 대체재, 인프라)
    → 수혜주 테이블: 종목명(티커), 현재가, 시총, PER, ROE, 영업이익률
  · "주목 포인트" 1~2줄 (이 종목을 왜 눈여겨봐야 하는지)

2. 📊 시장 온도 체크
- VIX, 10Y 국채금리, 달러인덱스, Fear & Greed — 각각 현재 수준 + 의미 해석
- 주요 지수 (S&P 500, 나스닥, 다우) 등락 + 한 줄 코멘트
- 금, 유가 동향 + 의미
- 전체적인 시장 분위기 한 줄 요약

3. ⚡ 오늘 주목할 이벤트
- 실적 발표 예정 종목 (서프라이즈 가능성 체크)
- 경제 지표 발표, 연준 일정 등
- 시장에 영향 줄 수 있는 이벤트

투자 권유/추천/매수 전략/목표가 제시 절대 금지!
"이 종목이 좋다"가 아니라 "이 종목이 이 이슈와 이렇게 연결돼 있어요"라는 교육적 톤을 유지하세요.
""" + SEO_INSTRUCTION


def _build_news_dive_prompt(
    analysis: dict,
    screened: list[CandidateScreenData],
    scan: MarketScanData,
    macro: MacroIndicators,
) -> str:
    """뉴스 분석 + 스크리닝 + 매크로를 최종 리포트 프롬프트로 변환한다."""
    parts = [f"## 분석 일자: {scan.scan_date}\n"]

    # 매크로 지표
    parts.append("## 매크로 지표")
    if macro.vix is not None:
        parts.append(f"- VIX: {macro.vix} ({macro.vix_change:+.2f})" if macro.vix_change is not None else f"- VIX: {macro.vix}")
    if macro.treasury_10y is not None:
        parts.append(f"- 10Y 국채금리: {macro.treasury_10y}% ({macro.treasury_10y_change:+.2f}%p)" if macro.treasury_10y_change is not None else f"- 10Y 국채금리: {macro.treasury_10y}%")
    if macro.dxy is not None:
        parts.append(f"- 달러인덱스(DXY): {macro.dxy} ({macro.dxy_change:+.2f})" if macro.dxy_change is not None else f"- 달러인덱스(DXY): {macro.dxy}")
    if macro.fear_greed_value is not None:
        parts.append(f"- Fear & Greed: {macro.fear_greed_value} ({macro.fear_greed_label})")
    if macro.sp500_close is not None:
        parts.append(f"- S&P 500: {macro.sp500_close:,.2f} ({macro.sp500_change_pct:+.2f}%)" if macro.sp500_change_pct is not None else f"- S&P 500: {macro.sp500_close:,.2f}")
    if macro.nasdaq_close is not None:
        parts.append(f"- 나스닥: {macro.nasdaq_close:,.2f} ({macro.nasdaq_change_pct:+.2f}%)" if macro.nasdaq_change_pct is not None else f"- 나스닥: {macro.nasdaq_close:,.2f}")
    if macro.dow_close is not None:
        parts.append(f"- 다우: {macro.dow_close:,.2f} ({macro.dow_change_pct:+.2f}%)" if macro.dow_change_pct is not None else f"- 다우: {macro.dow_close:,.2f}")
    if macro.gold_close is not None:
        parts.append(f"- 금: ${macro.gold_close:,.2f} ({macro.gold_change_pct:+.2f}%)" if macro.gold_change_pct is not None else f"- 금: ${macro.gold_close:,.2f}")
    if macro.wti_close is not None:
        parts.append(f"- WTI 유가: ${macro.wti_close:,.2f} ({macro.wti_change_pct:+.2f}%)" if macro.wti_change_pct is not None else f"- WTI 유가: ${macro.wti_close:,.2f}")

    # 뉴스 분석 결과
    parts.append("\n## 핵심 이슈 분석 (Claude #1 결과)")
    for i, story in enumerate(analysis.get("stories", []), 1):
        parts.append(f"\n### 이슈 {i}: {story.get('headline', '')}")
        parts.append(f"무슨 일: {story.get('what_happened', '')}")
        parts.append(f"왜 중요: {story.get('why_it_matters', '')}")
        affected = story.get("affected_tickers", [])
        if affected:
            parts.append(f"직접 영향: {', '.join(affected)}")
        beneficiaries = story.get("beneficiary_tickers", [])
        if beneficiaries:
            parts.append(f"숨은 수혜: {', '.join(beneficiaries)}")

    # 스크리닝 결과
    if screened:
        parts.append("\n## 언급 종목 재무지표 (Finnhub 실측)")
        for s in screened:
            cap = _fmt_money(s.market_cap * 1_000_000) if s.market_cap else "N/A"
            w52 = ""
            if s.week52_high and s.week52_low and s.close > 0:
                range_pct = (s.close - s.week52_low) / (s.week52_high - s.week52_low) * 100 if s.week52_high != s.week52_low else 50
                w52 = f", 52주 범위 내 {range_pct:.0f}% 위치"
            parts.append(
                f"- {s.name} ({s.ticker}): ${s.close:,.2f} ({s.change_pct_1d:+.2f}%), "
                f"시총 {cap}, "
                f"PER {_fmt_num(s.pe_ttm)}, PSR {_fmt_num(s.ps_ttm)}, PBR {_fmt_num(s.pb_annual)}, "
                f"ROE {_fmt_pct(s.roe_ttm)}, "
                f"매출총이익률 {_fmt_pct(s.gross_margin_ttm)}, 영업이익률 {_fmt_pct(s.operating_margin_ttm)}, "
                f"3년매출성장 {_fmt_pct(s.revenue_growth_3y)}, 3년EPS성장 {_fmt_pct(s.eps_growth_3y)}, "
                f"베타 {_fmt_num(s.beta)}, 애널리스트매수 {_fmt_pct(s.analyst_buy_pct)}"
                f"{w52}"
            )

    # 실적 캘린더
    if scan.earnings_today or scan.earnings_tomorrow:
        parts.append("\n## 실적 발표 캘린더")
        for label, items in [("오늘", scan.earnings_today), ("내일", scan.earnings_tomorrow)]:
            if items:
                parts.append(f"\n{label}:")
                for e in items:
                    eps = f" (EPS 예상 ${e.eps_estimate:.2f})" if e.eps_estimate else ""
                    parts.append(f"- {e.ticker}{eps}")

    # 주요 뉴스
    if scan.market_news:
        parts.append("\n## 시장 주요 뉴스")
        for n in scan.market_news[:10]:
            parts.append(f"- {n.headline}")
            if n.summary:
                parts.append(f"  {n.summary[:150]}")

    return "\n".join(parts)


def generate_news_dive_report(
    analysis: dict,
    screened: list[CandidateScreenData],
    scan: MarketScanData,
    macro: MacroIndicators,
) -> BriefingResult:
    """Stage 4: 뉴스 분석 + 재무지표 + 매크로로 최종 리포트를 생성한다."""
    prompt = _build_news_dive_prompt(analysis, screened, scan, macro)
    provider = ClaudeCliProvider(timeout=300)
    raw = provider.call(NEWS_DIVE_REPORT_PROMPT, prompt)
    raw = strip_code_block(raw)
    html, seo_title, slug, excerpt, tags = extract_seo_metadata(raw)

    title = seo_title or f"{date.today().strftime('%Y년 %m월 %d일')} 뉴스 딥다이브"
    logger.info("뉴스 딥다이브 리포트 생성 완료: %s", title)
    return BriefingResult(title=title, html=html, slug=slug, excerpt=excerpt, tags=tags)


async def run_news_dive_pipeline(email_to: list[str] | None = None) -> str:
    """뉴스 딥다이브 파이프라인 — 4단계.

    Stage 1 → 데이터 수집 (뉴스/시세 + 매크로 병렬)
    Stage 2 → 뉴스 분석 (Claude #1)
    Stage 3 → 종목 데이터 보강 (재무 스크리닝)
    Stage 4 → 최종 리포트 (Claude #2)
    """
    logger.info("뉴스 딥다이브 파이프라인 시작: %s", date.today())

    # Stage 1: 데이터 수집 (병렬)
    logger.info("[Stage 1] 시장 스캔 + 매크로 지표 수집...")
    scan_data, macro_data = await asyncio.gather(scan_market(), fetch_macro_indicators())
    logger.info("[Stage 1] 스캔 완료: 뉴스 %d건, 매크로 VIX=%s",
                len(scan_data.market_news), macro_data.vix)

    # Stage 2: 뉴스 분석 (Claude #1)
    logger.info("[Stage 2] 뉴스 분석 중...")
    analysis = analyze_news(scan_data, macro_data)
    mentioned_tickers = _extract_mentioned_tickers(analysis)
    logger.info("[Stage 2] 이슈 %d개, 언급 종목 %d개",
                len(analysis.get("stories", [])), len(mentioned_tickers))

    # Stage 3: 종목 데이터 보강
    logger.info("[Stage 3] %d개 종목 재무 스크리닝...", len(mentioned_tickers))
    screened = await screen_candidates(mentioned_tickers)
    logger.info("[Stage 3] 스크리닝 완료: %d개 종목 데이터 확보", len(screened))

    # Stage 4: 최종 리포트 (Claude #2)
    logger.info("[Stage 4] 뉴스 딥다이브 리포트 작성 중...")
    result = generate_news_dive_report(analysis, screened, scan_data, macro_data)

    # 저장 + 발송
    await _deliver(result, briefing_type="news_dive", email_to=email_to)

    return result.html


# ══════════════════════════════════════════════
# Mode B: 개별 종목 딥리서치 (기존)
# ══════════════════════════════════════════════


RESEARCH_SYSTEM_PROMPT = """당신은 2030 직장인을 위한 주식 심화 분석 에디터예요.
뉴닉(Newneek) 스타일의 친근한 톤으로, 하지만 내용은 증권사 리서치 수준의 심화 보고서를 작성해주세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "PER(주가수익비율, 낮을수록 저평가)")
- 숫자는 강조하되 맥락을 함께 제공
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
- 한 줄 판단: 매수/관망/매도 + 이유
- 현재가, 목표주가, 상승여력
- 핵심 포인트 3개 (불릿)

2. 🏢 사업 분석
- 뭘 하는 회사인지 쉽게 설명
- 매출 구성 (있으면 테이블)
- 경쟁 우위(moat)가 뭔지
- 동종업계 포지션 — peer 비교 테이블 (시총, PER, 마진 등)

3. 💰 재무 분석
- 최근 4분기 실적 트렌드 (테이블 권장: 매출, 영업이익, 순이익)
- 마진 변화 흐름
- FCF(잉여현금흐름) 상황
- 핵심 지표 peer 비교 테이블

4. 📈 밸류에이션
- PER/PBR/PS 현재 수준과 히스토리
- 52주 고저 대비 현재 위치
- Peer 대비 프리미엄/디스카운트
- 목표주가 산출 근거

5. ⚡ 최근 실적 & 뉴스
- 최근 실적 beat/miss 여부
- 가이던스 변화
- 애널리스트 추천 추이 (강력매수/매수/중립/매도 비율)
- 주요 뉴스 3-5건

6. ⚠️ 리스크 요인
- 사업 리스크, 재무 리스크, 시장 리스크 각 1-2개
- 구체적이고 현실적인 리스크만

7. 🎯 결론
- Bull 시나리오 (목표주가 상단)
- Base 시나리오 (목표주가)
- Bear 시나리오 (목표주가 하단)
- 최종 판단 한 줄

데이터가 없는 항목은 "데이터 미확보"로 표시하되, 가능한 범위에서 분석을 계속하세요.
숫자를 표시할 때 큰 수는 읽기 쉽게 (예: $1,234.5B, $56.7M) 변환하세요.
""" + SEO_INSTRUCTION


def _build_research_prompt(data: StockResearchData) -> str:
    """수집 데이터를 딥리서치 프롬프트로 변환한다."""
    parts = [f"## 종목: {data.ticker}\n"]

    if data.profile.name:
        p = data.profile
        cap_m = p.market_cap * 1_000_000
        parts.append("## 기업 프로필")
        parts.append(f"- 이름: {p.name}")
        parts.append(f"- 거래소: {p.exchange}, 산업: {p.industry}")
        parts.append(f"- 시가총액: {_fmt_money(cap_m)}, IPO: {p.ipo}, 국가: {p.country}")

    if data.quote.current > 0:
        q = data.quote
        parts.append(f"\n## 현재 시세")
        parts.append(f"- 현재가: ${q.current:,.2f} ({q.change_pct:+.2f}%)")
        parts.append(f"- 고/저: ${q.high:,.2f} / ${q.low:,.2f}, 전일: ${q.prev_close:,.2f}")

    if data.financials.pe_ttm is not None:
        f = data.financials
        parts.append(f"\n## 핵심 밸류에이션/재무지표")
        parts.append(f"- PER {_fmt_num(f.pe_ttm)}, PBR {_fmt_num(f.pb_annual)}, PSR {_fmt_num(f.ps_ttm)}")
        parts.append(f"- ROE {_fmt_pct(f.roe_ttm)}, ROI {_fmt_pct(f.roi_ttm)}")
        parts.append(f"- 매출총이익률 {_fmt_pct(f.gross_margin_ttm)}, 영업이익률 {_fmt_pct(f.operating_margin_ttm)}, 순이익률 {_fmt_pct(f.net_margin_ttm)}")
        parts.append(f"- 부채비율 {_fmt_num(f.debt_equity)}, 유동비율 {_fmt_num(f.current_ratio)}, 베타 {_fmt_num(f.beta)}")
        parts.append(f"- 52주 고가 ${f.week52_high or 0:,.2f} ({f.week52_high_date}), 저가 ${f.week52_low or 0:,.2f} ({f.week52_low_date})")
        parts.append(f"- 3년 매출성장 {_fmt_pct(f.revenue_growth_3y)}, 3년 EPS성장 {_fmt_pct(f.eps_growth_3y)}")

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
            parts.append(f"- {r.period}: 매출 {_fmt_money(r.total_revenue)}, 영업이익 {_fmt_money(r.operating_income)}, 순이익 {_fmt_money(r.net_income)}, EBITDA {_fmt_money(r.ebitda)}")

    if quarterly_income:
        parts.append(f"\n## 분기별 손익계산서")
        for r in quarterly_income[:4]:
            parts.append(f"- {r.period}: 매출 {_fmt_money(r.total_revenue)}, 영업이익 {_fmt_money(r.operating_income)}, 순이익 {_fmt_money(r.net_income)}")

    annual_bs = [r for r in data.balance_sheets if r.period_type == "annual"]
    if annual_bs:
        parts.append(f"\n## 연간 대차대조표")
        for r in annual_bs[:4]:
            parts.append(f"- {r.period}: 자산 {_fmt_money(r.total_assets)}, 부채 {_fmt_money(r.total_liabilities)}, 자본 {_fmt_money(r.stockholders_equity)}, 현금 {_fmt_money(r.total_cash)}, 순부채 {_fmt_money(r.net_debt)}")

    annual_cf = [r for r in data.cash_flows if r.period_type == "annual"]
    if annual_cf:
        parts.append(f"\n## 연간 현금흐름표")
        for r in annual_cf[:4]:
            parts.append(f"- {r.period}: 영업CF {_fmt_money(r.operating_cf)}, Capex {_fmt_money(r.capital_expenditure)}, FCF {_fmt_money(r.free_cash_flow)}")

    if data.price_history:
        prices = data.price_history
        latest = prices[-1].close
        year_ago = prices[0].close
        year_return = ((latest - year_ago) / year_ago * 100) if year_ago else 0
        parts.append(f"\n## 1년 주가: {year_return:+.1f}% (${min(p.close for p in prices):,.2f} ~ ${max(p.close for p in prices):,.2f})")

    if data.sec_filings:
        parts.append(f"\n## 최근 SEC 공시")
        for f in data.sec_filings:
            parts.append(f"- [{f.form_type}] {f.filing_date}: {f.description}")

    if data.peer_financials:
        parts.append(f"\n## Peer 기업 비교")
        for pf in data.peer_financials:
            cap = _fmt_money(pf.market_cap * 1_000_000) if pf.market_cap else "N/A"
            parts.append(f"- {pf.name} ({pf.ticker}): 시총 {cap}, PER {_fmt_num(pf.pe_ttm)}, ROE {_fmt_pct(pf.roe_ttm)}, 영업이익률 {_fmt_pct(pf.operating_margin_ttm)}")

    return "\n".join(parts)


def summarize_research(data: StockResearchData) -> BriefingResult:
    """딥 리서치 데이터로 개별 종목 보고서를 생성한다."""
    prompt = _build_research_prompt(data)
    provider = ClaudeCliProvider(timeout=300)
    raw = provider.call(RESEARCH_SYSTEM_PROMPT, prompt)
    raw = strip_code_block(raw)
    html, seo_title, slug, excerpt, tags = extract_seo_metadata(raw)

    name = data.profile.name or data.ticker
    title = seo_title or f"{name} ({data.ticker}) 심화 분석 리포트"
    logger.info("딥리서치 보고서 완료: %s", title)
    return BriefingResult(title=title, html=html, slug=slug, excerpt=excerpt, tags=tags)


async def run_deep_research_pipeline(ticker: str, email_to: list[str] | None = None) -> str:
    """개별 종목 딥리서치 파이프라인."""
    logger.info("딥리서치 파이프라인 시작: %s", ticker)

    data = await fetch_stock_research(ticker)
    result = summarize_research(data)

    await _deliver(result, briefing_type=f"research_{ticker.lower()}", email_to=email_to)

    return result.html
