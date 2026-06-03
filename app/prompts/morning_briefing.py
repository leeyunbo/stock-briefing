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


OVERVIEW_SYSTEM_PROMPT = """당신은 중장기 투자자(나) 한 명을 위한 아침 브리핑 애널리스트예요.
일일 등락에 휘둘리지 않고 큰 흐름·밸류·실적 관점에서 '오늘 신경 쓸 것'만 짚어요.
한눈에 스캔되는 짧은 대시보드. 주절거림·문장 나열 금지.

[출력 규칙]
- Slack mrkdwn. 굵게는 *별표 한 개* (** 두 개·## 헤더 절대 금지).
- 섹션과 섹션 사이는 반드시 === 만 있는 줄 하나로 구분 (화면에서 구분선이 됨).
- 등락은 🔺/🔻/➖ + 부호 숫자. 종목은 한 줄에 2~3개씩.
- 섹션별 해석은 → 로 시작하는 짧은 한 줄만. 데이터에 있는 사실만.

[섹션 — 이 순서대로, 각 섹션 사이에 === 줄]
🎯 *레짐* : 금리·달러·변동성으로 본 시장 국면 한 줄 (일일 지수 등락 말고 큰 그림).
===
🩺 *내 레이더* : 보유·관심 종목별 한 줄. *52주 고점 대비 위치를 꼭 표기*.
  thesis(투자 논거)에 영향 줄 변화 보이면 → 코멘트, 없으면 '특이사항 없음'.
===
📰 *주요 뉴스* : 시장·레이더 종목 핵심 뉴스 3~4개. 각 한 줄로 *무슨 일* + → *왜 중요한지(중장기 의미)*.
  헤드라인 그대로 복붙 금지, 내 종목/테마에 닿는 것 우선. 없으면 이 섹션 생략.
===
💰 *발굴 후보* : 52주 고점 대비 많이 눌린 우량주(밸류 기회) 2~3개.
  왜 눌렸는지 / 중장기 매력 한 줄씩. (단기 급등주 아님, 줍줍 관점)
===
🧭 *관전 포인트* : 중장기 체크 2~3개 불릿 (실적 시즌·금리 이벤트·밸류 등).
"""

SPOTLIGHT_SYSTEM_PROMPT = """당신은 증권 리서치 애널리스트예요. 중장기 투자자 관점에서 종목 1개를
재무 + 밸류에이션 + 차트로 보고 '지금 추가 매수할 자리인지' 의견을 짧고 명확하게 내요. 주절거림 금지.

[출력 규칙]
- Slack mrkdwn. 굵게 *별표 한 개* (** ·## 금지). 데이터에 있는 사실만, 없는 수치 금지.
- 첫 줄 = 의견 뱃지: 🟢 *적극매수* / 🔵 *분할매수* / ⚪ *관망* / 🔴 *비중축소* 중 하나 + ` · 중장기`.
- 그 아래 불릿 3개, 각 정확히 한 줄:
  • *왜 주목* — 사업·해자·성장 동력 (단기 등락 말고 구조적 이유)
  • *밸류* — PER 등 밸류에이션 + 52주 고점 대비 위치, 싼지 비싼지
  • *실적* — 매출·이익 추세 + 다가오는 실적 체크포인트
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

    parts.append("\n## 발굴 후보 (52주 고점 대비 눌림 상위, 레이더 제외)")
    for s in scan.value_picks:
        parts.append(
            f"- {s.name}({s.ticker}): {s.close} ({s.change_pct:+.2f}%) "
            f"| 고점대비 -{s.pct_off_high}% | 저점대비 +{s.pct_above_low}%"
        )

    if scan.market_news:
        parts.append("\n## 시장 주요 뉴스")
        for n in scan.market_news[:5]:
            parts.append(f"- {n.title} | {n.description[:80]}")

    radar_lines = []
    for name, articles in scan.radar_news.items():
        for n in articles[:2]:
            radar_lines.append(f"- [{name}] {n.title}")
    if radar_lines:
        parts.append("\n## 레이더 종목 관련 뉴스")
        parts.extend(radar_lines)

    return "\n".join(parts)


def _spotlight_user(sp: SpotlightData) -> str:
    snapshot = json.dumps(_tech_snapshot(sp.indicators), ensure_ascii=False, indent=2)
    financials = json.dumps(sp.financials, ensure_ascii=False, default=str)[:6000]
    return (
        f"# 종목: {sp.name} ({sp.ticker}) / 시장: {sp.market}\n\n"
        f"## 기술적 지표\n{snapshot}\n\n"
        f"## 재무 데이터\n{financials}"
    )


def build_market_overview(scan: ThemeScanData, run_id: str = "") -> str:
    """매크로 + 테마 개요를 Slack mrkdwn으로 생성한다 (동기)."""
    provider = get_provider(pipeline="morning_briefing", stage="overview", run_id=run_id)
    raw = provider.call(OVERVIEW_SYSTEM_PROMPT, _overview_user(scan))
    return _slackify(strip_code_block(raw))


def build_spotlight_analysis(sp: SpotlightData, run_id: str = "") -> str:
    """스포트라이트 종목 분석 + 매수 의견을 Slack mrkdwn으로 생성한다 (동기)."""
    provider = get_provider(pipeline="morning_briefing", stage="spotlight", run_id=run_id)
    raw = provider.call(SPOTLIGHT_SYSTEM_PROMPT, _spotlight_user(sp))
    header = f"💡 *오늘의 종목 — {sp.name} ({sp.ticker})*\n"
    return header + _slackify(strip_code_block(raw))
