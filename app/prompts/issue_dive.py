"""이슈 딥다이브 — LLM #1 이슈 선정 + LLM #2 피처 기사 생성."""

import json
import logging
import re
from datetime import date

from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.collector.news import NewsArticle
from app.pipeline.base import BriefingResult
from app.prompts import fmt_money, fmt_num, fmt_pct
from app.prompts.news_dive import _format_macro_lines
from app.summarizer import SEO_INSTRUCTION, WRITING_STYLE_RULES, extract_seo_metadata, strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# LLM #1: 이슈 선정 프롬프트
# ══════════════════════════════════════════════


PICK_ISSUE_PROMPT = """당신은 글로벌 매크로 전략가이자 시니어 에디터예요.
오늘 날짜: {today}

아래 데이터(뉴스, 시세, 매크로 지표)를 분석해서 **오늘 가장 중요한 이슈 1개**를 선정하세요.

선정 기준 (우선순위 순):
1. 시장을 가장 크게 움직인 뉴스 (등락 TOP과 직접 연결)
2. 정책 변화, 실적 서프라이즈, 산업 구조 변화
3. 향후 2~4주간 시장에 지속적 영향을 줄 이슈
4. 독자가 깊이 있는 분석을 원할 만한 복잡한 이슈

중요:
- 경제 이벤트의 날짜를 추측하지 마세요. 데이터에 명시된 일정만 언급하세요.
- 반드시 **1개의 이슈만** 선정하세요.
- **주제 반복 금지 규칙** (반드시 준수):
  - 아래 "이미 다룬 주제" 목록에 나온 종목/이슈와 같은 주제를 선정하면 안 됩니다.
  - "다른 각도", "후속 보도", "상황 변화" 등 어떤 이유로든 같은 종목/이슈를 다시 다루지 마세요.
  - 예: "마벨 실적"을 이미 다뤘으면 "마벨 폭등 이유"도 금지입니다. 완전히 다른 주제를 선택하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "topic": "이슈 주제 (한국어, 2~5단어)",
  "headline": "이슈 제목 (한국어, 1문장)",
  "why_picked": "왜 이 이슈를 선정했는지 2~3문장",
  "search_keywords": ["추가 리서치용 네이버 검색 키워드 5개"],
  "related_tickers": ["관련 종목 티커 최대 10개"]
}}
"""


def _build_pick_issue_prompt(scan: MarketScanData, macro: MacroIndicators) -> str:
    """스캔 + 매크로 데이터를 이슈 선정 프롬프트로 변환한다."""
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

    if scan.market_news:
        parts.append("\n## 시장 주요 뉴스")
        for n in scan.market_news:
            related = f" [{n.related}]" if n.related else ""
            parts.append(f"- {n.headline}{related}")
            if n.summary:
                parts.append(f"  {n.summary[:200]}")

    return "\n".join(parts)


def _fetch_recent_issue_titles(days: int = 7) -> list[str]:
    """최근 N일간 발행된 이슈 딥다이브 제목을 DB에서 가져온다 (동기 방식)."""
    from datetime import timedelta
    from sqlalchemy import create_engine, select, text
    from app.core.config import get_settings
    from app.core.models import Briefing, BriefingType

    try:
        db_url = get_settings().database_url
        # async URL을 sync URL로 변환
        sync_url = db_url.replace("sqlite+aiosqlite://", "sqlite://")
        engine = create_engine(sync_url)
        cutoff = date.today() - timedelta(days=days)
        with engine.connect() as conn:
            result = conn.execute(
                select(Briefing.title).where(
                    Briefing.briefing_type == BriefingType.ISSUE_DIVE,
                    Briefing.date >= cutoff,
                )
            )
            titles = [row[0] for row in result.all()]
        engine.dispose()
        return titles
    except Exception as e:
        logger.warning("최근 이슈 제목 조회 실패: %s", e)
        return []


def _extract_banned_keywords(titles: list[str]) -> list[str]:
    """제목 목록에서 반복 등장하는 핵심 키워드를 추출한다."""
    import re as _re
    from collections import Counter

    # 불용어
    stopwords = {
        "이슈", "딥다이브", "분석", "시나리오", "시그널", "경고", "의미", "배경",
        "핵심", "급등", "급락", "폭등", "폭락", "충격", "위기", "비밀", "신호",
        "오늘", "내일", "시장", "종목", "동반", "하락", "상승", "반등", "돌파",
        "가지", "가격", "전망", "영향", "대비", "속보", "최고가", "사상",
    }

    words = Counter()
    for title in titles:
        # 한글 2글자 이상 단어 + 영문 단어 추출
        tokens = _re.findall(r'[가-힣]{2,}|[A-Z]{2,}', title)
        for t in tokens:
            if t not in stopwords and len(t) >= 2:
                words[t] += 1

    # 2회 이상 등장한 키워드 반환
    return [w for w, c in words.most_common(15) if c >= 2]


def pick_top_issue(scan: MarketScanData, macro: MacroIndicators, run_id: str = "") -> dict:
    """LLM #1: 전체 뉴스에서 가장 중요한 이슈 1개를 선정한다."""
    prompt = _build_pick_issue_prompt(scan, macro)

    # 이미 다룬 주제 추가 — 제목 + 금지 키워드 명시
    recent_titles = _fetch_recent_issue_titles()
    if recent_titles:
        prompt += "\n\n## ⛔ 이미 다룬 주제 (아래 종목/이슈는 절대 선정 금지)\n"
        for t in recent_titles:
            prompt += f"- {t}\n"
        # 제목에서 핵심 키워드 추출하여 명시
        banned = _extract_banned_keywords(recent_titles)
        if banned:
            prompt += f"\n금지 키워드: {', '.join(banned)}\n"
            prompt += "위 키워드가 포함된 이슈는 선정하지 마세요.\n"

    system_prompt = PICK_ISSUE_PROMPT.replace("{today}", date.today().isoformat())
    provider = get_cli_provider(timeout=120, pipeline="issue_dive", stage="pick_issue", run_id=run_id)
    raw = provider.call(system_prompt, prompt)
    raw = strip_code_block(raw.strip())

    json_match = re.search(r'\{[\s\S]+\}', raw)
    if json_match:
        raw = json_match.group()

    try:
        result = json.loads(raw)
        for key in ("topic", "headline", "search_keywords", "related_tickers"):
            if key not in result:
                raise ValueError(f"{key} 키 없음")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("이슈 선정 JSON 파싱 실패: %s / raw=%s", e, raw[:300])
        raise RuntimeError(f"이슈 선정 실패: {raw[:300]}") from e


# ══════════════════════════════════════════════
# LLM #2: 피처 기사 생성 프롬프트
# ══════════════════════════════════════════════


ISSUE_DIVE_ARTICLE_PROMPT = """당신은 경제 매거진의 시니어 에디터예요.
하나의 이슈를 깊이 파는 장문 피처 기사를 작성하세요.
오늘 날짜: {today}

중요:
- 경제 이벤트의 날짜를 추측하지 마세요. 데이터에 명시된 일정만 언급하세요.
- 이미 발표된 지표를 "예정" 또는 "임박"으로 쓰면 오보입니다.
- 추가 수집한 뉴스의 다양한 시각을 반영하세요.

톤앤매너:
- "~요" 체 사용 (교육적이고 친근한 톤)
- 어려운 용어는 괄호로 쉽게 풀어주기
- 투자 권유/추천 절대 금지. "이런 일이 일어나고 있어요" 톤 유지
- <strong> 태그로 핵심 강조
- 이모지는 섹션 제목에만 1개씩

종목 표기 규칙:
- 반드시 "NVDA (엔비디아)" 형식 (티커 + 한국어 회사명)
- 처음 언급할 때만 풀네임, 이후는 티커만 사용 가능

차트 삽입 규칙:
- 독자 이해에 도움이 되는 위치에 차트 지시자를 삽입하세요
- 형식: <!-- CHART:타입 key=value -->
- 지원 타입:
  * line: 주가/지수 추이 → <!-- CHART:line ticker=NFLX period=1mo title="넷플릭스 주가 추이 (1개월)" -->
  * compare: 여러 종목 비교 → <!-- CHART:compare ticker=NFLX,DIS,CMCSA period=3mo title="스트리밍 3사 주가 비교" -->
  * bar: 등락률 비교 → <!-- CHART:bar tickers=NFLX,DIS,CMCSA,WBD period=5d title="스트리밍 종목 주간 등락률" -->
- period 옵션: 5d(5일), 1mo(1개월), 3mo(3개월), 6mo(6개월), 1y(1년)
- ticker는 미국 주식 티커 사용 (예: AAPL, ^GSPC, ^IXIC, ^KS11)
- 기사당 2~4개 차트를 적절한 위치에 배치하세요
- 차트 지시자는 반드시 별도 줄에 단독으로 작성하세요

작성 규칙:
- HTML 형식 (이메일 발송용)
- <h2> 태그 (인라인 스타일 넣지 마세요, 후처리에서 자동 적용)
- 비교 데이터는 <table> 활용
- <div>, <style>, CSS class, 인라인 style 속성 사용 금지
- 본문 맨 위에 날짜/제목 쓰지 마세요
- 분량: 4000~5000단어 (한국어 기준)

섹션 구성 (6개 섹션, 순서 반드시 준수):

1. <h2>📌 무슨 일이 일어났나</h2>
- 팩트 위주의 타임라인
- 핵심 숫자와 데이터를 정확히 제시
- 누가, 무엇을, 언제, 왜 했는지 명확히

2. <h2>🔍 배경과 맥락</h2>
- 이 이슈가 왜 지금 터졌는지 구조적 배경
- 관련 산업/정책/글로벌 트렌드와의 연결
- 독자가 "아, 그래서 이런 거구나" 할 수 있는 해설

3. <h2>📊 시장 임팩트 분석</h2>
- 수혜주/피해주 테이블 (종목명(티커), 현재가, 시총, PER, ROE, 영업이익률, 영향 방향)
- 각 종목이 왜 영향받는지 밸류체인 관점 설명
- 섹터/산업 전체에 미치는 영향
- <h3>🇰🇷 한국 시장 영향</h3>으로 소섹션을 만들어 환율, 코스피, 국내 수혜/피해 종목을 여기에 모아서 작성
- 다른 섹션에서는 한국 관련 내용을 반복하지 마세요

4. <h2>📜 역사적 유사 사례</h2>
- 과거에 비슷한 이슈가 있었을 때 시장이 어떻게 반응했는지
- 당시와 현재의 공통점/차이점
- 역사에서 배울 수 있는 교훈

5. <h2>🔮 시나리오 분석</h2>
- Bull 시나리오: 가장 낙관적 전개 + 근거
- Base 시나리오: 가장 가능성 높은 전개 + 근거
- Bear 시나리오: 가장 비관적 전개 + 근거
- 각 시나리오별 관련 종목 영향

6. <h2>🎯 결론: 앞으로 지켜볼 포인트</h2>
- 향후 1~4주 내 확인해야 할 핵심 이벤트/데이터
- 이 이슈의 전개 방향을 가늠할 수 있는 시그널
- 투자자가 주의해야 할 리스크

투자 권유/추천/매수 전략/목표가 제시 절대 금지!
"이 종목이 좋다"가 아니라 "이 이슈가 이렇게 전개될 수 있어요"라는 교육적 톤을 유지하세요.
""" + WRITING_STYLE_RULES + SEO_INSTRUCTION


def _build_issue_dive_prompt(
    issue: dict,
    additional_news: list[NewsArticle],
    screened: list[CandidateScreenData],
    scan: MarketScanData,
    macro: MacroIndicators,
) -> str:
    """이슈 선정 결과 + 추가 수집 뉴스 + 스크리닝을 기사 생성 프롬프트로 변환한다."""
    parts = [f"## 분석 일자: {scan.scan_date}\n"]

    # 선정된 이슈
    parts.append("## 선정된 이슈")
    parts.append(f"- 주제: {issue.get('topic', '')}")
    parts.append(f"- 제목: {issue.get('headline', '')}")
    parts.append(f"- 선정 이유: {issue.get('why_picked', '')}")

    # 매크로 지표
    parts.append("\n## 매크로 지표")
    parts.extend(_format_macro_lines(macro))

    # 원본 시장 뉴스
    if scan.market_news:
        parts.append("\n## 원본 시장 뉴스")
        for n in scan.market_news[:15]:
            related = f" [{n.related}]" if n.related else ""
            parts.append(f"- {n.headline}{related}")
            if n.summary:
                parts.append(f"  {n.summary[:200]}")

    # 추가 수집 뉴스 (상위 20건으로 제한)
    if additional_news:
        capped = additional_news[:20]
        parts.append(f"\n## 추가 수집 뉴스 ({len(capped)}건)")
        for n in capped:
            parts.append(f"- {n.title}")
            if n.description:
                parts.append(f"  {n.description[:150]}")

    # 스크리닝 결과
    if screened:
        parts.append("\n## 관련 종목 재무지표 (Finnhub 실측)")
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

    return "\n".join(parts)


def generate_issue_dive_article(
    issue: dict,
    additional_news: list[NewsArticle],
    screened: list[CandidateScreenData],
    scan: MarketScanData,
    macro: MacroIndicators,
    run_id: str = "",
) -> BriefingResult:
    """LLM #2: 선정된 이슈로 장문 피처 기사를 생성한다."""
    prompt = _build_issue_dive_prompt(issue, additional_news, screened, scan, macro)
    system_prompt = ISSUE_DIVE_ARTICLE_PROMPT.replace("{today}", date.today().isoformat())
    provider = get_cli_provider(timeout=600, pipeline="issue_dive", stage="generate_article", run_id=run_id)
    raw = provider.call(system_prompt, prompt)
    raw = strip_code_block(raw)
    seo = extract_seo_metadata(raw)

    title = seo.title or f"{date.today().strftime('%Y년 %m월 %d일')} 이슈 딥다이브: {issue.get('topic', '')}"
    logger.info("이슈 딥다이브 기사 생성 완료: %s", title)
    return BriefingResult(title=title, html=seo.html, slug=seo.slug, excerpt=seo.excerpt, tags=seo.tags, focus_keyword=seo.focus_keyword, image_keyword=seo.image_keyword)
