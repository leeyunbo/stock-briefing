"""차트 지시자 파싱 + 데이터 수집 + matplotlib 렌더링.

LLM이 본문에 삽입한 <!-- CHART:... --> 지시자를 파싱하고,
실제 주가 데이터를 가져와 차트 이미지를 생성한다.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.font_manager as fm
import yfinance as yf

# 한글 폰트 설정 (macOS: Apple SD Gothic Neo, Linux: Nanum Gothic)
_KR_FONTS = ["Apple SD Gothic Neo", "Nanum Gothic", "NanumGothic", "Malgun Gothic"]
for _font_name in _KR_FONTS:
    if any(f.name == _font_name for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _font_name
        break
plt.rcParams["axes.unicode_minus"] = False

logger = logging.getLogger(__name__)

# ── MoneyDive 차트 스타일 ──

_COLORS = {
    "blue": "#3182F6",
    "red": "#F04452",
    "green": "#1DB177",
    "orange": "#E67E22",
    "purple": "#8B5CF6",
    "gray": "#8B95A1",
}

_PALETTE = ["#3182F6", "#F04452", "#1DB177", "#E67E22", "#8B5CF6", "#4E5968"]


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    """MoneyDive 브랜드 스타일 적용."""
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E5E8EB")
    ax.spines["bottom"].set_color("#E5E8EB")
    ax.tick_params(colors="#4E5968", labelsize=9)
    ax.grid(axis="y", color="#F2F3F5", linewidth=0.8)
    ax.set_axisbelow(True)


# ── 차트 지시자 파싱 ──

_CHART_PATTERN = re.compile(
    r"<!--\s*CHART:([\w]+)\s+(.*?)\s*-->",
    re.IGNORECASE,
)


def _parse_params(raw: str) -> dict[str, str]:
    """key=value 쌍을 파싱한다. value에 공백이 있으면 따옴표로 감싼다."""
    params: dict[str, str] = {}
    # key="value with spaces" 또는 key=value
    for m in re.finditer(r'(\w+)=(?:"([^"]+)"|(\S+))', raw):
        params[m.group(1)] = m.group(2) or m.group(3)
    return params


def parse_chart_directives(html: str) -> list[dict[str, Any]]:
    """HTML에서 <!-- CHART:type key=value --> 지시자를 추출한다."""
    directives = []
    for m in _CHART_PATTERN.finditer(html):
        chart_type = m.group(1).lower()
        params = _parse_params(m.group(2))
        directives.append({
            "type": chart_type,
            "params": params,
            "placeholder": m.group(0),
        })
    return directives


# ── 데이터 수집 ──


def _fetch_price_data(ticker: str, period: str = "1mo") -> Any:
    """yfinance로 주가 데이터를 가져온다."""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period)
        if df.empty:
            logger.warning("주가 데이터 없음: %s", ticker)
            return None
        return df
    except Exception as e:
        logger.warning("주가 데이터 수집 실패: %s — %s", ticker, e)
        return None


def _fetch_multi_price_data(tickers: list[str], period: str = "1mo") -> dict:
    """여러 종목의 주가 데이터를 가져온다."""
    result = {}
    for ticker in tickers:
        df = _fetch_price_data(ticker, period)
        if df is not None:
            result[ticker] = df
    return result


# ── 차트 렌더링 ──


def _render_line(params: dict[str, str]) -> bytes | None:
    """주가 추이 라인 차트."""
    ticker = params.get("ticker", "")
    period = params.get("period", "1mo")
    title = params.get("title", f"{ticker} 주가 추이")

    if not ticker:
        return None

    # 여러 종목 지원 (쉼표 구분)
    tickers = [t.strip() for t in ticker.split(",")]

    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    _apply_style(ax, fig)

    if len(tickers) == 1:
        df = _fetch_price_data(tickers[0], period)
        if df is None:
            plt.close(fig)
            return None
        ax.plot(df.index, df["Close"], color=_COLORS["blue"], linewidth=2)
        ax.fill_between(df.index, df["Close"], alpha=0.08, color=_COLORS["blue"])
    else:
        data = _fetch_multi_price_data(tickers, period)
        if not data:
            plt.close(fig)
            return None
        for i, (t, df) in enumerate(data.items()):
            # 정규화 (첫날 = 100)
            normalized = df["Close"] / df["Close"].iloc[0] * 100
            ax.plot(df.index, normalized, color=_PALETTE[i % len(_PALETTE)],
                    linewidth=2, label=t)
        ax.legend(fontsize=9, frameon=False)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    ax.set_title(title, fontsize=13, fontweight="bold", color="#191F28",
                 pad=12, loc="left")
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _render_bar(params: dict[str, str]) -> bytes | None:
    """등락률 비교 바 차트."""
    tickers_raw = params.get("tickers", "")
    period = params.get("period", "5d")
    title = params.get("title", "등락률 비교")

    if not tickers_raw:
        return None

    tickers = [t.strip() for t in tickers_raw.split(",")]
    changes = {}
    for t in tickers:
        df = _fetch_price_data(t, period)
        if df is not None and len(df) >= 2:
            pct = ((df["Close"].iloc[-1] / df["Close"].iloc[0]) - 1) * 100
            changes[t] = pct

    if not changes:
        return None

    fig, ax = plt.subplots(figsize=(8, max(3, len(changes) * 0.6)), dpi=150)
    _apply_style(ax, fig)

    names = list(changes.keys())
    values = list(changes.values())
    colors = [_COLORS["red"] if v < 0 else _COLORS["blue"] for v in values]

    bars = ax.barh(names, values, color=colors, height=0.55, edgecolor="none")

    # 값 레이블
    for bar, val in zip(bars, values):
        x_pos = bar.get_width()
        ha = "left" if val >= 0 else "right"
        offset = 0.3 if val >= 0 else -0.3
        ax.text(x_pos + offset, bar.get_y() + bar.get_height() / 2,
                f"{val:+.1f}%", va="center", ha=ha, fontsize=9, color="#4E5968")

    ax.set_title(title, fontsize=13, fontweight="bold", color="#191F28",
                 pad=12, loc="left")
    ax.axvline(x=0, color="#E5E8EB", linewidth=1)
    ax.spines["left"].set_visible(False)
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── 렌더러 매핑 ──

_RENDERERS = {
    "line": _render_line,
    "bar": _render_bar,
    "compare": _render_line,  # compare는 line의 다종목 모드로 처리
}


def render_chart(directive: dict) -> bytes | None:
    """단일 차트 지시자를 렌더링한다."""
    renderer = _RENDERERS.get(directive["type"])
    if not renderer:
        logger.warning("지원하지 않는 차트 타입: %s", directive["type"])
        return None

    try:
        return renderer(directive["params"])
    except Exception as e:
        logger.warning("차트 렌더링 실패: %s — %s", directive, e)
        return None
