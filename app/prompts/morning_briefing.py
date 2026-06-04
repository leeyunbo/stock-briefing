"""개인 아침 브리핑 — 시장 개요 + 스포트라이트 분석 프롬프트.

출력은 Slack mrkdwn. 거시 + 테마 개요 1개, 스포트라이트 종목별 분석 N개.
"""

import json
import logging

from app.collector.spotlight import SpotlightData
from app.collector.technical import TechnicalIndicators
from app.collector.theme_scan import ThemeScanData
from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)


OVERVIEW_SYSTEM_PROMPT = """당신은 중장기 투자자(나) 한 명을 위한 아침 브리핑 작성자예요.
일일 등락에 휘둘리지 않고 큰 흐름·밸류·실적 관점에서 '오늘 신경 쓸 것'만 짚어요.
한눈에 스캔되는 짧은 대시보드. 주절거림·문장 나열 금지.

[말투 — 토스(toss) 스타일: 일반인도 쉽게]
- 어려운 금융 용어는 괄호로 쉽게 풀어줘요. 예: thesis(이 종목을 산 이유), PER(주가가 이익의 몇 배인지), HBM(AI에 쓰는 고성능 메모리).
- 따뜻하고 대화하듯 "~해요"체. 전문가인 척·딱딱한 표현 금지.
- 숫자엔 꼭 맥락을 붙여요. 예: "3% 빠졌어요 — 한 달 만에 가장 큰 하락이에요".
- 쉽게 쓰되 핵심은 빠뜨리지 마세요. 쉽다 ≠ 얕다.

[출력 규칙]
- Slack mrkdwn. 굵게는 *별표 한 개* (** 두 개·## 헤더 절대 금지).
- 섹션과 섹션 사이는 반드시 === 만 있는 줄 하나로 구분 (화면에서 구분선이 됨).
- 등락은 🔺/🔻/➖ + 부호 숫자. 종목은 한 줄에 2~3개씩.
- 섹션별 해석은 → 로 시작하는 짧은 한 줄만. 데이터에 있는 사실만.

[자료 활용]
- 시세·밸류 숫자는 '구조화 데이터'에서, 인사이트·동향은 '웹 리서치'에서 가져와 *합성*하세요.
- 웹 리서치에서 가져온 사실엔 출처(매체/기관)를 괄호로 짧게 인용. 웹 리서치에 없는 내용을 지어내지 마세요.

[섹션 — 이 순서대로, 각 섹션 사이에 === 줄]
🎯 *오늘의 큰 그림* : 금리·달러·변동성 + 웹 리서치 거시 요인으로 본 시장 국면 한 줄 (일일 등락 말고 큰 그림).
===
📅 *이벤트 캘린더* : 이번 주 예정된 실적 발표·경제지표·정책 일정 (웹 리서치 기반). 내 종목/테마 관련 우선. 없으면 생략.
===
🩺 *내 레이더* : 보유·관심 종목별 한 줄. *52주 고점 대비 위치 표기* + 웹 리서치의 애널리스트 뷰·이벤트로 thesis 코멘트(출처).
  영향 줄 변화 없으면 '특이사항 없음'.
===
📰 *핵심 인사이트* : 웹 리서치에서 건진 *진짜 중요한* 인사이트 3~4개. 각 한 줄 *무슨 일* + → *중장기 의미*(출처). 헤드라인 복붙 금지.
===
🧭 *관전 포인트* : 중장기 체크 2~3개 불릿 (실적 시즌·금리 이벤트·밸류 등).
"""

SPOTLIGHT_SYSTEM_PROMPT = """당신은 증권 리서치 애널리스트예요. 중장기 투자자 관점에서 종목 1개를
재무 + 밸류에이션 + 차트로 보고 '지금 추가 매수할 자리인지' 의견을 짧고 명확하게 내요. 주절거림 금지.

[출력 규칙]
- Slack mrkdwn. 굵게 *별표 한 개* (** ·## 금지). 데이터에 있는 사실만, 없는 수치 금지.
- 재무 숫자는 '재무 데이터'에서, 동향·애널리스트 뷰는 '웹 리서치'에서. 웹 리서치 사실엔 출처(매체) 짧게 인용.
- 첫 줄 = 의견 뱃지: 🟢 *적극매수* / 🔵 *분할매수* / ⚪ *관망* / 🔴 *비중축소* 중 하나 + ` · 중장기`.
- 그 아래 불릿 4개, 각 한 줄:
  • *왜 주목* — 사업·해자·성장 동력 (구조적 이유)
  • *밸류* — PER 등 + 52주 고점 대비 위치, 싼지 비싼지
  • *실적* — 매출·이익 추세 + 다가오는 실적 체크포인트
  • *시장 시각* — 웹 리서치의 애널리스트 의견·목표주가·최근 이슈(출처)
- 마지막 줄: _개인 참고용, 투자권유 아님_
"""


def _slackify(text: str) -> str:
    """모델이 마크다운으로 흘린 경우 Slack mrkdwn으로 보정한다."""
    lines = []
    for line in text.splitlines():
        st = line.lstrip()
        if st.startswith("#"):
            t = st.lstrip("#").strip()
            lines.append(f"*{t}*" if t else "")
        else:
            lines.append(line)
    return "\n".join(lines).replace("**", "*")


def _tech_snapshot(ind: TechnicalIndicators | None) -> dict:
    if not ind:
        return {}
    return {
        "현재가": ind.latest_close,
        "등락률%": ind.latest_change_pct,
        "RSI": round(ind.latest_rsi, 1),
        "SMA20": round(ind.latest_sma20, 2),
        "SMA50": round(ind.latest_sma50, 2),
        "SMA200": round(ind.latest_sma200, 2),
        "MACD": round(ind.latest_macd, 3),
        "MACD_signal": round(ind.latest_macd_signal, 3),
        "볼린저_%B": round(ind.latest_bb_pct_b, 2),
        "52주최고": ind.week52_high,
        "52주최저": ind.week52_low,
        "지지선": [round(x, 2) for x in ind.support_levels[:3]],
        "저항선": [round(x, 2) for x in ind.resistance_levels[:3]],
    }


def _overview_user(scan: ThemeScanData) -> str:
    m = scan.macro
    parts = ["## 매크로 (큰 흐름)"]
    parts.append(
        f"- 나스닥 {m.nasdaq_close}({m.nasdaq_change_pct}%) S&P {m.sp500_close}({m.sp500_change_pct}%) "
        f"다우 {m.dow_close}({m.dow_change_pct}%)"
    )
    parts.append(
        f"- VIX {m.vix}({m.vix_change}) 美10Y {m.treasury_10y}%({m.treasury_10y_change}) "
        f"DXY {m.dxy}({m.dxy_change}) 금 {m.gold_close}({m.gold_change_pct}%) WTI {m.wti_close}({m.wti_change_pct}%)"
    )
    if m.fear_greed_value is not None:
        parts.append(f"- Fear&Greed: {m.fear_greed_value}({m.fear_greed_label})")

    parts.append("\n## 내 레이더 (보유·관심)")
    for s in scan.watchlist:
        parts.append(
            f"- {s.name}({s.ticker}): {s.close} ({s.change_pct:+.2f}%) "
            f"| 52주고 {s.year_high} 대비 -{s.pct_off_high}% | 52주저 대비 +{s.pct_above_low}%"
        )

    parts.append("\n## 테마 시세 (발굴 유니버스)")
    for theme, stocks in scan.themes.items():
        if not stocks:
            continue
        parts.append(f"### {theme}")
        for s in stocks:
            parts.append(f"- {s.name}({s.ticker}): {s.close} ({s.change_pct:+.2f}%) | 고점대비 -{s.pct_off_high}%")

    if scan.market_news:
        parts.append("\n## 시장 주요 뉴스 (네이버)")
        for n in scan.market_news[:5]:
            parts.append(f"- {n.title} | {n.description[:80]}")

    return "\n".join(parts)


def _research_block(research: dict | None, scan: ThemeScanData) -> str:
    """웹 리서치 결과를 프롬프트용 텍스트로 변환한다."""
    if not research:
        return ""
    parts = ["\n\n========== 웹 리서치 (인사이트 소스) =========="]
    if research.get("market"):
        parts.append("\n### [웹] 거시·시장·이벤트 캘린더\n" + research["market"])
    if research.get("themes"):
        parts.append("\n### [웹] 테마 동향\n" + research["themes"])
    stocks = research.get("stocks") or {}
    name_by_ticker = {s.ticker: s.name for s in scan.watchlist}
    for ticker, text in stocks.items():
        if text:
            parts.append(f"\n### [웹] {name_by_ticker.get(ticker, ticker)}({ticker})\n{text}")
    return "\n".join(parts)


def _spotlight_user(sp: SpotlightData, research_text: str = "") -> str:
    snapshot = json.dumps(_tech_snapshot(sp.indicators), ensure_ascii=False, indent=2)
    financials = json.dumps(sp.financials, ensure_ascii=False, default=str)[:6000]
    web = f"\n\n## 웹 리서치 (애널리스트 뷰·최근 이슈)\n{research_text}" if research_text else ""
    return (
        f"# 종목: {sp.name} ({sp.ticker}) / 시장: {sp.market}\n\n"
        f"## 기술적 지표\n{snapshot}\n\n"
        f"## 재무 데이터\n{financials}{web}"
    )


def build_market_overview(scan: ThemeScanData, research: dict | None = None, run_id: str = "") -> str:
    """매크로 + 테마 개요 + 웹 리서치를 Slack mrkdwn으로 합성한다 (동기)."""
    provider = get_provider(pipeline="morning_briefing", stage="overview", run_id=run_id)
    user = _overview_user(scan) + _research_block(research, scan)
    raw = provider.call(OVERVIEW_SYSTEM_PROMPT, user)
    return _slackify(strip_code_block(raw))


def build_spotlight_analysis(sp: SpotlightData, research_text: str = "", run_id: str = "") -> str:
    """스포트라이트 종목 분석 + 매수 의견을 Slack mrkdwn으로 생성한다 (동기)."""
    provider = get_provider(pipeline="morning_briefing", stage="spotlight", run_id=run_id)
    raw = provider.call(SPOTLIGHT_SYSTEM_PROMPT, _spotlight_user(sp, research_text))
    header = f"💡 *오늘의 종목 — {sp.name} ({sp.ticker})*\n"
    return header + _slackify(strip_code_block(raw))
