"""차트 기술적 분석 — LLM 프롬프트 + 호출."""

import logging
from datetime import date

from app.collector.technical import TechnicalIndicators
from app.summarizer import strip_code_block
from app.tracing import get_cli_provider

logger = logging.getLogger(__name__)


# ── 시스템 프롬프트 ──

CHART_ANALYSIS_SYSTEM = """\
당신은 기술적 분석(Technical Analysis) 전문가입니다.
제공된 기술적 지표 데이터를 바탕으로 종합적인 기술적 분석 리포트를 작성하세요.

## 분석 항목 (반드시 모두 포함)

### 1. 추세 분석 (Trend)
- 이동평균선(SMA 20/50/200) 배열로 추세 방향 판단
- 골든크로스/데드크로스 발생 여부
- 현재가와 이동평균선의 거리 (이격도)

### 2. 모멘텀 분석 (Momentum)
- RSI 과매수/과매도 상태 및 다이버전스
- MACD 시그널 교차, 히스토그램 추세

### 3. 변동성 분석 (Volatility)
- 볼린저밴드 %B 위치 (상단/중단/하단)
- 밴드 폭 수축/확대 여부 (스퀴즈)

### 4. 거래량 분석 (Volume)
- 최근 거래량 vs 20일 평균 비교
- 가격 변동과 거래량 동반 여부

### 5. 지지/저항 분석
- 주요 지지선, 저항선 위치와 현재가와의 거리

### 6. 종합 판단
- 매수/매도/관망 시그널 종합
- 단기(1~2주) / 중기(1~3개월) 전망
- 주의할 리스크 요인

## 출력 규칙
- HTML로 출력 (마크다운 아님)
- <h2>, <h3>, <p>, <ul>, <li>, <strong>, <span> 태그 사용
- 시그널을 색상으로 표시:
  - 매수/긍정: <span style="color:#1DB177">...</span>
  - 매도/부정: <span style="color:#F04452">...</span>
  - 중립: <span style="color:#8B95A1">...</span>
- 숫자와 구체적 근거를 반드시 포함
- 분석은 객관적이고 균형 잡힌 시각 유지
- 한국어로 작성
"""


# ── 프롬프트 빌더 ──


def build_ta_prompt(ind: TechnicalIndicators) -> str:
    """지표 스냅샷을 프롬프트 텍스트로 변환한다."""
    currency = "원" if ind.market == "KR" else "$"

    # SMA 시그널 판단
    sma_signals = []
    if ind.latest_sma20 and ind.latest_sma50:
        if ind.latest_sma20 > ind.latest_sma50:
            sma_signals.append("SMA20 > SMA50 (단기 상승 배열)")
        else:
            sma_signals.append("SMA20 < SMA50 (단기 하락 배열)")
    if ind.latest_sma50 and ind.latest_sma200:
        if ind.latest_sma50 > ind.latest_sma200:
            sma_signals.append("SMA50 > SMA200 (중기 상승 배열)")
        else:
            sma_signals.append("SMA50 < SMA200 (중기 하락 배열)")

    parts = [
        f"## 기술적 분석 데이터 — {ind.name or ind.ticker}",
        f"- 날짜: {date.today().isoformat()}",
        f"- 시장: {ind.market}",
        f"- 현재가: {ind.latest_close:,.2f}{currency} ({ind.latest_change_pct:+.2f}%)",
        f"- 52주 고가: {ind.week52_high:,.2f}{currency}",
        f"- 52주 저가: {ind.week52_low:,.2f}{currency}",
        f"- 52주 고가 대비: {((ind.latest_close / ind.week52_high - 1) * 100):+.1f}%",
        "",
        "## 이동평균",
        f"- SMA 20: {ind.latest_sma20:,.2f}{currency}",
        f"- SMA 50: {ind.latest_sma50:,.2f}{currency}",
        f"- SMA 200: {ind.latest_sma200:,.2f}{currency}",
    ]
    for sig in sma_signals:
        parts.append(f"- {sig}")

    parts.extend([
        "",
        "## RSI (14)",
        f"- 현재 RSI: {ind.latest_rsi:.1f}",
        f"- 상태: {'과매수' if ind.latest_rsi >= 70 else '과매도' if ind.latest_rsi <= 30 else '중립 구간'}",
        "",
        "## MACD (12, 26, 9)",
        f"- MACD Line: {ind.latest_macd:.4f}",
        f"- Signal Line: {ind.latest_macd_signal:.4f}",
        f"- Histogram: {ind.latest_macd_histogram:.4f}",
        f"- 상태: {'MACD > Signal (매수 시그널)' if ind.latest_macd > ind.latest_macd_signal else 'MACD < Signal (매도 시그널)'}",
        "",
        "## 볼린저밴드 (20, 2)",
        f"- 상단: {ind.latest_bb_upper:,.2f}{currency}",
        f"- 하단: {ind.latest_bb_lower:,.2f}{currency}",
        f"- %B: {ind.latest_bb_pct_b:.1f}%",
        f"- 위치: {'상단 돌파 (과열)' if ind.latest_bb_pct_b > 100 else '하단 이탈 (과매도)' if ind.latest_bb_pct_b < 0 else '밴드 내'}",
        "",
        "## 거래량",
        f"- 최근 거래량: {ind.latest_volume:,}",
    ])

    if ind.volume_sma20:
        latest_vol_sma = ind.volume_sma20[-1] if ind.volume_sma20[-1] != 0 else 1
        vol_ratio = ind.latest_volume / latest_vol_sma if latest_vol_sma else 0
        parts.append(f"- 20일 평균 거래량: {latest_vol_sma:,.0f}")
        parts.append(f"- 거래량 비율: {vol_ratio:.2f}x")

    parts.extend([
        "",
        "## 지지/저항",
        f"- 저항선: {', '.join(f'{r:,.2f}{currency}' for r in ind.resistance_levels) or 'N/A'}",
        f"- 지지선: {', '.join(f'{s:,.2f}{currency}' for s in ind.support_levels) or 'N/A'}",
    ])

    return "\n".join(parts)


# ── LLM 호출 ──


def generate_analysis(ind: TechnicalIndicators, run_id: str = "") -> str:
    """LLM으로 기술적 분석 텍스트를 생성한다. HTML 반환."""
    prompt = build_ta_prompt(ind)
    provider = get_cli_provider(
        timeout=300, pipeline="chart_analysis", stage="generate_analysis", run_id=run_id,
    )
    raw = provider.call(CHART_ANALYSIS_SYSTEM, prompt)
    return strip_code_block(raw).strip()
