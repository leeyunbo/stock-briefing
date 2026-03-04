"""차트 기술적 분석 파이프라인.

ticker 입력 → 시장 판별 → OHLCV 수집 → 지표 계산 → 차트 렌더링 → LLM 해석 → HTML 리포트.
WordPress/이메일 발행 없이 HTML 파일로 출력.
"""

from __future__ import annotations

import base64
import logging
from asyncio import to_thread
from datetime import date
from pathlib import Path
from typing import Any

from app.collector.kr_stock_research import detect_market, resolve_kr_ticker
from app.collector.technical import (
    TechnicalIndicators,
    calculate_indicators,
    fetch_kr_current_price,
    fetch_kr_name,
    fetch_ohlcv_kr,
    fetch_ohlcv_us,
)
from app.pipeline.base import PipelineContext, run_steps
from app.tracing import generate_run_id

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")


# ── 파이프라인 컨텍스트 ──


class ChartAnalysisContext(PipelineContext, total=False):
    ticker: str
    market: str
    indicators: TechnicalIndicators
    charts: dict[str, bytes]
    analysis_html: str
    output_path: str


# ── Step 1: 데이터 수집 + 지표 계산 ──


async def collect_data(ctx: ChartAnalysisContext) -> None:
    """시장 판별 → OHLCV 수집 → 기술적 지표 계산."""
    ticker = ctx["ticker"]
    market = detect_market(ticker)
    ctx["market"] = market

    logger.info("[차트분석 Step 1] %s 시장: %s — OHLCV 수집 중...", ticker, market)

    if market == "KR":
        code = await resolve_kr_ticker(ticker)
        df = await fetch_ohlcv_kr(code)
        ind = calculate_indicators(df, code, market)
        ind.name = await fetch_kr_name(code)
        # 현재가 업데이트 (실시간)
        current, change_pct = await fetch_kr_current_price(code)
        if current > 0:
            ind.latest_close = current
            ind.latest_change_pct = change_pct
        ind.ticker = code
    else:
        df = await to_thread(fetch_ohlcv_us, ticker)
        ind = calculate_indicators(df, ticker, market)
        # yfinance에서 종목명 가져오기
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            ind.name = t.info.get("shortName", ticker)
        except Exception:
            ind.name = ticker

    ctx["indicators"] = ind
    logger.info("[차트분석 Step 1] 지표 계산 완료: %s (RSI=%.1f, MACD=%.4f)",
                ind.name, ind.latest_rsi, ind.latest_macd)


# ── Step 2: 차트 렌더링 ──


async def render_charts(ctx: ChartAnalysisContext) -> None:
    """4개 차트를 렌더링한다."""
    from app.publishing.ta_chart import render_all_charts

    logger.info("[차트분석 Step 2] 차트 렌더링 중...")
    charts = await to_thread(render_all_charts, ctx["indicators"])
    ctx["charts"] = charts
    logger.info("[차트분석 Step 2] %d개 차트 렌더링 완료", len(charts))


# ── Step 3: LLM 기술적 분석 ──


async def generate_report(ctx: ChartAnalysisContext) -> None:
    """LLM으로 기술적 분석 텍스트를 생성한다."""
    from app.prompts.chart_analysis import generate_analysis

    logger.info("[차트분석 Step 3] LLM 기술적 분석 생성 중...")
    analysis_html = await to_thread(generate_analysis, ctx["indicators"], ctx["run_id"])
    ctx["analysis_html"] = analysis_html
    logger.info("[차트분석 Step 3] 분석 텍스트 생성 완료 (%d chars)", len(analysis_html))


# ── Step 4: HTML 리포트 빌드 ──


async def build_html(ctx: ChartAnalysisContext) -> None:
    """차트 + 지표 테이블 + LLM 분석 → HTML 리포트 조합."""
    ind = ctx["indicators"]
    charts = ctx["charts"]
    analysis = ctx["analysis_html"]

    currency = "원" if ind.market == "KR" else "$"
    fmt = lambda v: f"{v:,.0f}" if ind.market == "KR" else f"{v:,.2f}"

    # 차트 이미지 → base64 img 태그
    chart_imgs = {}
    chart_titles = {
        "price": "주가 · 이동평균 · 볼린저밴드",
        "rsi": "RSI (14)",
        "macd": "MACD (12, 26, 9)",
        "volume": "거래량",
    }
    for key, png_bytes in charts.items():
        b64 = base64.b64encode(png_bytes).decode()
        chart_imgs[key] = (
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="{chart_titles.get(key, key)}" '
            f'style="width:100%;height:auto;border-radius:8px;" />'
        )

    # 지표 시그널 판단
    def rsi_signal():
        if ind.latest_rsi >= 70:
            return "과매수", "#F04452"
        if ind.latest_rsi <= 30:
            return "과매도", "#1DB177"
        return "중립", "#8B95A1"

    def macd_signal():
        if ind.latest_macd > ind.latest_macd_signal:
            return "매수", "#1DB177"
        return "매도", "#F04452"

    def bb_signal():
        if ind.latest_bb_pct_b > 80:
            return "과열", "#F04452"
        if ind.latest_bb_pct_b < 20:
            return "과매도", "#1DB177"
        return "중립", "#8B95A1"

    def trend_signal():
        if ind.latest_sma20 and ind.latest_sma50 and ind.latest_sma200:
            if ind.latest_close > ind.latest_sma20 > ind.latest_sma50 > ind.latest_sma200:
                return "강한 상승", "#1DB177"
            if ind.latest_close < ind.latest_sma20 < ind.latest_sma50 < ind.latest_sma200:
                return "강한 하락", "#F04452"
            if ind.latest_close > ind.latest_sma50:
                return "상승 추세", "#1DB177"
            return "하락 추세", "#F04452"
        return "N/A", "#8B95A1"

    rsi_s, rsi_c = rsi_signal()
    macd_s, macd_c = macd_signal()
    bb_s, bb_c = bb_signal()
    trend_s, trend_c = trend_signal()

    change_color = "#F04452" if ind.latest_change_pct >= 0 else "#3182F6"
    change_sign = "+" if ind.latest_change_pct >= 0 else ""

    html = f"""\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ind.name or ind.ticker} 기술적 분석 리포트</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Nanum Gothic', sans-serif;
         background: #F7F8FA; color: #191F28; line-height: 1.6; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 24px 16px; }}
  .header {{ background: #FFFFFF; border-radius: 16px; padding: 32px; margin-bottom: 20px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .header h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 8px; }}
  .header .price {{ font-size: 32px; font-weight: 700; margin: 12px 0 4px; }}
  .header .change {{ font-size: 18px; font-weight: 600; }}
  .header .meta {{ font-size: 13px; color: #8B95A1; margin-top: 8px; }}
  .card {{ background: #FFFFFF; border-radius: 12px; padding: 24px; margin-bottom: 16px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .card h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 16px; color: #191F28; }}
  .chart-img {{ margin: 0 -8px; }}
  .chart-img img {{ display: block; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; padding: 10px 12px; background: #F7F8FA; color: #4E5968;
       font-weight: 600; border-bottom: 2px solid #E5E8EB; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #F2F3F5; }}
  .signal {{ font-weight: 700; font-size: 13px; padding: 3px 10px; border-radius: 12px;
             display: inline-block; }}
  .analysis-content h2 {{ font-size: 18px; margin: 24px 0 12px; padding-bottom: 8px;
                          border-bottom: 2px solid #F2F3F5; }}
  .analysis-content h3 {{ font-size: 15px; margin: 16px 0 8px; color: #333D4B; }}
  .analysis-content p {{ margin: 8px 0; color: #4E5968; font-size: 15px; }}
  .analysis-content ul {{ margin: 8px 0 8px 20px; }}
  .analysis-content li {{ margin: 4px 0; color: #4E5968; font-size: 14px; }}
  .footer {{ text-align: center; padding: 32px 16px; font-size: 12px; color: #B0B8C1; }}
  .footer p {{ margin: 4px 0; }}
</style>
</head>
<body>
<div class="container">

  <!-- 헤더 -->
  <div class="header">
    <h1>{ind.name or ind.ticker}</h1>
    <div class="meta">{ind.market} · {ind.ticker} · {date.today().strftime('%Y년 %m월 %d일')}</div>
    <div class="price">{fmt(ind.latest_close)}{currency}</div>
    <div class="change" style="color:{change_color}">
      {change_sign}{ind.latest_change_pct:.2f}%
    </div>
    <div class="meta">52주 고가 {fmt(ind.week52_high)}{currency} · 저가 {fmt(ind.week52_low)}{currency}</div>
  </div>

  <!-- 차트: 주가 -->
  <div class="card">
    <div class="chart-img">{chart_imgs.get("price", "")}</div>
  </div>

  <!-- 차트: RSI -->
  <div class="card">
    <div class="chart-img">{chart_imgs.get("rsi", "")}</div>
  </div>

  <!-- 차트: MACD -->
  <div class="card">
    <div class="chart-img">{chart_imgs.get("macd", "")}</div>
  </div>

  <!-- 차트: 거래량 -->
  <div class="card">
    <div class="chart-img">{chart_imgs.get("volume", "")}</div>
  </div>

  <!-- 지표 요약 테이블 -->
  <div class="card">
    <h2>기술적 지표 요약</h2>
    <table>
      <thead>
        <tr><th>지표</th><th>현재값</th><th>시그널</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>추세 (SMA 배열)</td>
          <td>SMA20 {fmt(ind.latest_sma20)} / SMA50 {fmt(ind.latest_sma50)} / SMA200 {fmt(ind.latest_sma200)}</td>
          <td><span class="signal" style="color:{trend_c};background:{trend_c}15">{trend_s}</span></td>
        </tr>
        <tr>
          <td>RSI (14)</td>
          <td>{ind.latest_rsi:.1f}</td>
          <td><span class="signal" style="color:{rsi_c};background:{rsi_c}15">{rsi_s}</span></td>
        </tr>
        <tr>
          <td>MACD</td>
          <td>MACD {ind.latest_macd:.4f} / Signal {ind.latest_macd_signal:.4f}</td>
          <td><span class="signal" style="color:{macd_c};background:{macd_c}15">{macd_s}</span></td>
        </tr>
        <tr>
          <td>볼린저밴드 %B</td>
          <td>{ind.latest_bb_pct_b:.1f}%</td>
          <td><span class="signal" style="color:{bb_c};background:{bb_c}15">{bb_s}</span></td>
        </tr>
        <tr>
          <td>지지선</td>
          <td>{', '.join(f'{s:,.2f}{currency}' for s in ind.support_levels) or 'N/A'}</td>
          <td></td>
        </tr>
        <tr>
          <td>저항선</td>
          <td>{', '.join(f'{r:,.2f}{currency}' for r in ind.resistance_levels) or 'N/A'}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- LLM 기술적 분석 -->
  <div class="card">
    <h2>AI 기술적 분석</h2>
    <div class="analysis-content">
      {analysis}
    </div>
  </div>

  <!-- 푸터 -->
  <div class="footer">
    <p>본 리포트는 AI가 생성한 기술적 분석 자료이며, 투자 권유가 아닙니다.</p>
    <p>투자 판단의 책임은 투자자 본인에게 있습니다.</p>
    <p style="margin-top:8px;">Generated by MoneyDive · {date.today().isoformat()}</p>
  </div>

</div>
</body>
</html>"""

    ctx["result_html"] = html
    logger.info("[차트분석 Step 4] HTML 리포트 빌드 완료 (%d chars)", len(html))


# ── Step 5: 파일 저장 ──


async def save_file(ctx: ChartAnalysisContext) -> None:
    """output/ 디렉토리에 HTML 파일을 저장한다."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    ind = ctx["indicators"]
    ticker_slug = ind.ticker.replace(".", "_")
    filename = f"chart_analysis_{ticker_slug}_{date.today().isoformat()}.html"
    path = OUTPUT_DIR / filename

    path.write_text(ctx["result_html"], encoding="utf-8")
    ctx["output_path"] = str(path)
    logger.info("[차트분석 Step 5] 파일 저장: %s", path)


# ── 파이프라인 ──


CHART_ANALYSIS_STEPS = [
    collect_data,
    render_charts,
    generate_report,
    build_html,
    save_file,
]


async def run_chart_analysis_pipeline(
    ticker: str,
    email_to: list[str] | None = None,
) -> str:
    """차트 기술적 분석 파이프라인을 실행한다.

    Returns:
        생성된 HTML 파일 경로.
    """
    logger.info("차트 분석 파이프라인 시작: %s (%s)", ticker, date.today())
    ctx: ChartAnalysisContext = {
        "run_id": generate_run_id(),
        "pipeline": "chart_analysis",
        "ticker": ticker,
    }
    await run_steps(CHART_ANALYSIS_STEPS, ctx)
    return ctx.get("output_path", "")
