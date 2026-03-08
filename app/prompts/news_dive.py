"""뉴스 딥다이브 — 시스템 프롬프트, 프롬프트 빌더, AI 호출."""

import json
import logging
import re
from datetime import date

from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.pipeline.base import BriefingResult
from app.prompts import fmt_money, fmt_num, fmt_pct
from app.summarizer import SEO_INSTRUCTION, WRITING_STYLE_RULES, extract_seo_metadata, strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


def _format_macro_lines(macro: MacroIndicators) -> list[str]:
    """매크로 지표를 프롬프트 라인으로 변환한다."""
    lines: list[str] = []
    if macro.vix is not None:
        lines.append(f"- VIX: {macro.vix} ({macro.vix_change:+.2f})" if macro.vix_change is not None else f"- VIX: {macro.vix}")
    if macro.treasury_10y is not None:
        lines.append(f"- 10Y 국채금리: {macro.treasury_10y}% ({macro.treasury_10y_change:+.2f}%p)" if macro.treasury_10y_change is not None else f"- 10Y 국채금리: {macro.treasury_10y}%")
    if macro.dxy is not None:
        lines.append(f"- 달러인덱스(DXY): {macro.dxy} ({macro.dxy_change:+.2f})" if macro.dxy_change is not None else f"- 달러인덱스(DXY): {macro.dxy}")
    if macro.fear_greed_value is not None:
        lines.append(f"- Fear & Greed: {macro.fear_greed_value} ({macro.fear_greed_label})")
    if macro.sp500_close is not None:
        lines.append(f"- S&P 500: {macro.sp500_close:,.2f} ({macro.sp500_change_pct:+.2f}%)" if macro.sp500_change_pct is not None else f"- S&P 500: {macro.sp500_close:,.2f}")
    if macro.nasdaq_close is not None:
        lines.append(f"- 나스닥: {macro.nasdaq_close:,.2f} ({macro.nasdaq_change_pct:+.2f}%)" if macro.nasdaq_change_pct is not None else f"- 나스닥: {macro.nasdaq_close:,.2f}")
    if macro.dow_close is not None:
        lines.append(f"- 다우: {macro.dow_close:,.2f} ({macro.dow_change_pct:+.2f}%)" if macro.dow_change_pct is not None else f"- 다우: {macro.dow_close:,.2f}")
    if macro.gold_close is not None:
        lines.append(f"- 금: ${macro.gold_close:,.2f} ({macro.gold_change_pct:+.2f}%)" if macro.gold_change_pct is not None else f"- 금: ${macro.gold_close:,.2f}")
    if macro.wti_close is not None:
        lines.append(f"- WTI 유가: ${macro.wti_close:,.2f} ({macro.wti_change_pct:+.2f}%)" if macro.wti_change_pct is not None else f"- WTI 유가: ${macro.wti_close:,.2f}")
    return lines


# ── Stage 2: 뉴스 분석 (Claude #1) ──


NEWS_ANALYSIS_PROMPT = """당신은 글로벌 매크로 전략가이자 경제 유튜버의 리서처예요.
오늘 날짜: {today}

아래 데이터(뉴스, 시세, 매크로 지표)를 분석해서:
1. 오늘 가장 중요한 뉴스/이슈 2~3개를 선정하세요
2. 각 이슈가 왜 중요한지, 어떤 종목이 영향받는지 분석하세요

중요: 경제 이벤트(지표 발표, 연준 회의 등)의 날짜를 추측하지 마세요. 데이터에 명시된 일정만 언급하세요. 이미 발표된 지표를 "예정" 또는 "임박"으로 언급하면 안 됩니다.

이슈 선정 기준:
- 시장을 실제로 움직인 뉴스 (등락 TOP과 연결)
- 정책 변화, 실적 서프라이즈, 산업 구조 변화
- "왜 이런 일이 일어나고 있는지" 설명할 수 있는 이슈
- **주제 반복 금지**: 아래 "이미 다룬 주제"에 나온 종목/이슈는 어떤 각도로든 다시 선정하지 마세요. 완전히 다른 이슈를 선택하세요.

종목 분석 기준:
- affected_tickers: 이 이슈로 직접 영향받는 종목 (상승이든 하락이든)
- beneficiary_tickers: 숨은 수혜주 (밸류체인, 부품, 대체재, 인프라)
  → 이게 핵심! 나스닥 100 밖 종목도 괜찮아요.

휴장일인 경우:
- 개별 종목 시세(등락률, 거래량) 데이터가 제공되지 않아요
- 뉴스 내용을 기반으로 이슈를 선정하고, 관련 종목을 분석해주세요

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


def _build_news_analysis_prompt(scan: MarketScanData, macro: MacroIndicators) -> str:
    """스캔 + 매크로 데이터를 뉴스 분석 프롬프트로 변환한다."""
    parts = [f"## 스캔 일자: {scan.scan_date}\n"]

    parts.append("## 매크로 지표")
    parts.extend(_format_macro_lines(macro))

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


def _fetch_recent_news_dive_titles(days: int = 7) -> list[str]:
    """최근 N일간 발행된 뉴스 딥다이브 제목을 DB에서 가져온다 (동기 방식)."""
    from datetime import timedelta
    from sqlalchemy import create_engine, select
    from app.core.config import get_settings
    from app.core.models import Briefing, BriefingType

    try:
        db_url = get_settings().database_url
        sync_url = db_url.replace("sqlite+aiosqlite://", "sqlite://")
        engine = create_engine(sync_url)
        cutoff = date.today() - timedelta(days=days)
        with engine.connect() as conn:
            result = conn.execute(
                select(Briefing.title).where(
                    Briefing.briefing_type.in_([BriefingType.NEWS_DIVE, BriefingType.ISSUE_DIVE]),
                    Briefing.date >= cutoff,
                )
            )
            titles = [row[0] for row in result.all()]
        engine.dispose()
        return titles
    except Exception as e:
        logger.warning("최근 뉴스 제목 조회 실패: %s", e)
        return []


def analyze_news(scan: MarketScanData, macro: MacroIndicators, run_id: str = "") -> dict:
    """Stage 2: Claude에게 뉴스+매크로를 주고 핵심 이슈 + 관련 종목을 도출한다."""
    prompt = _build_news_analysis_prompt(scan, macro)

    # 이미 다룬 주제 추가
    recent_titles = _fetch_recent_news_dive_titles()
    if recent_titles:
        prompt += "\n\n## 이미 다룬 주제 (같은 각도로 반복 금지)\n"
        for t in recent_titles:
            prompt += f"- {t}\n"

    system_prompt = NEWS_ANALYSIS_PROMPT.replace("{today}", date.today().isoformat())
    provider = get_cli_provider(timeout=180, pipeline="news_dive", stage="analyze_news", run_id=run_id)
    raw = provider.call(system_prompt, prompt)
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


# ── Stage 4: 뉴스 딥다이브 리포트 (Claude #2) ──


NEWS_DIVE_REPORT_PROMPT = """당신은 경제 유튜버 스타일의 시장 코멘터리 에디터예요.
"이걸 사세요"가 아니라 "이런 일이 일어나고 있어요"를 전달하는 게 핵심이에요.
오늘 날짜: {today}

중요: 경제 이벤트(지표 발표, FOMC, 연준 일정 등)의 날짜를 추측하지 마세요. 데이터에 명시된 일정만 언급하세요. 이미 발표된 지표를 "예정" 또는 "임박"으로 쓰면 오보입니다.

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

휴장일인 경우:
- 개별 종목 현재가/등락률을 언급하지 마세요 (최신 데이터가 아니에요)
- "📊 시장 온도 체크"에서 매크로 지표 해석에 집중하세요
- 수혜주 테이블에서 현재가/등락 컬럼은 제외하세요
- "⚡ 오늘 주목할 이벤트"에서 실적 발표 예정은 생략하세요

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
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION


def _build_news_dive_prompt(
    analysis: dict,
    screened: list[CandidateScreenData],
    scan: MarketScanData,
    macro: MacroIndicators,
) -> str:
    """뉴스 분석 + 스크리닝 + 매크로를 최종 리포트 프롬프트로 변환한다."""
    parts = [f"## 분석 일자: {scan.scan_date}\n"]

    parts.append("## 매크로 지표")
    parts.extend(_format_macro_lines(macro))

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
            cap = fmt_money(s.market_cap * 1_000_000) if s.market_cap else "N/A"
            w52 = ""
            if s.week52_high and s.week52_low and s.close > 0:
                range_pct = (s.close - s.week52_low) / (s.week52_high - s.week52_low) * 100 if s.week52_high != s.week52_low else 50
                w52 = f", 52주 범위 내 {range_pct:.0f}% 위치"
            price_part = f"${s.close:,.2f} ({s.change_pct_1d:+.2f}%), " if s.close > 0 else ""
            parts.append(
                f"- {s.name} ({s.ticker}): {price_part}"
                f"시총 {cap}, "
                f"PER {fmt_num(s.pe_ttm)}, PSR {fmt_num(s.ps_ttm)}, PBR {fmt_num(s.pb_annual)}, "
                f"ROE {fmt_pct(s.roe_ttm)}, "
                f"매출총이익률 {fmt_pct(s.gross_margin_ttm)}, 영업이익률 {fmt_pct(s.operating_margin_ttm)}, "
                f"3년매출성장 {fmt_pct(s.revenue_growth_3y)}, 3년EPS성장 {fmt_pct(s.eps_growth_3y)}, "
                f"베타 {fmt_num(s.beta)}, 애널리스트매수 {fmt_pct(s.analyst_buy_pct)}"
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
    run_id: str = "",
) -> BriefingResult:
    """Stage 4: 뉴스 분석 + 재무지표 + 매크로로 최종 리포트를 생성한다."""
    prompt = _build_news_dive_prompt(analysis, screened, scan, macro)
    system_prompt = NEWS_DIVE_REPORT_PROMPT.replace("{today}", date.today().isoformat())
    provider = get_cli_provider(timeout=600, pipeline="news_dive", stage="generate_report", run_id=run_id)
    raw = provider.call(system_prompt, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    title = seo.title or f"{date.today().strftime('%Y년 %m월 %d일')} 뉴스 딥다이브"
    logger.info("뉴스 딥다이브 리포트 생성 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword)
