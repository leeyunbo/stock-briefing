"""기술적 분석 차트 렌더링 — matplotlib.

4개 차트:
1) 주가 + SMA 20/50/200 + 볼린저밴드
2) RSI + 과매수(70)/과매도(30)
3) MACD + Signal + Histogram
4) 거래량 바 + 20일 SMA
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import matplotlib.font_manager as fm
import numpy as np

if TYPE_CHECKING:
    from app.collector.technical import TechnicalIndicators

# 한글 폰트
_KR_FONTS = ["Apple SD Gothic Neo", "Nanum Gothic", "NanumGothic", "Malgun Gothic"]
for _font_name in _KR_FONTS:
    if any(f.name == _font_name for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _font_name
        break
plt.rcParams["axes.unicode_minus"] = False

logger = logging.getLogger(__name__)

# ── 스타일 (chart.py 재사용) ──

_COLORS = {
    "blue": "#3182F6",
    "red": "#F04452",
    "green": "#1DB177",
    "orange": "#E67E22",
    "purple": "#8B5CF6",
    "gray": "#8B95A1",
    "light_gray": "#E5E8EB",
    "bg": "#FFFFFF",
    "text": "#191F28",
    "sub_text": "#4E5968",
    "grid": "#F2F3F5",
}


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    """MoneyDive 브랜드 스타일 적용."""
    fig.patch.set_facecolor(_COLORS["bg"])
    ax.set_facecolor(_COLORS["bg"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_COLORS["light_gray"])
    ax.spines["bottom"].set_color(_COLORS["light_gray"])
    ax.tick_params(colors=_COLORS["sub_text"], labelsize=9)
    ax.grid(axis="y", color=_COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def _format_xaxis(ax: plt.Axes, dates: list) -> None:
    """X축 날짜 포맷."""
    if len(dates) > 120:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    else:
        ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)


def _to_dates(date_strings: list[str]):
    """문자열 날짜를 matplotlib용 datetime으로 변환."""
    import pandas as pd
    return pd.to_datetime(date_strings)


def _fig_to_bytes(fig: plt.Figure) -> bytes:
    """Figure를 PNG bytes로 변환."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_COLORS["bg"], dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── 차트 1: 주가 + SMA + 볼린저밴드 ──


def render_price_chart(ind: TechnicalIndicators) -> bytes:
    """주가 + SMA 20/50/200 + 볼린저밴드."""
    dates = _to_dates(ind.dates)
    closes = np.array(ind.closes)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    _apply_style(ax, fig)

    # 볼린저밴드 (배경)
    bb_upper = np.array(ind.bb_upper)
    bb_lower = np.array(ind.bb_lower)
    valid = (bb_upper != 0) & (bb_lower != 0)
    if valid.any():
        ax.fill_between(dates[valid], bb_upper[valid], bb_lower[valid],
                        alpha=0.08, color=_COLORS["blue"], label="볼린저밴드")

    # 주가
    ax.plot(dates, closes, color=_COLORS["text"], linewidth=1.5, label="종가", zorder=3)

    # SMA
    sma20 = np.array(ind.sma20)
    sma50 = np.array(ind.sma50)
    sma200 = np.array(ind.sma200)

    mask20 = sma20 != 0
    mask50 = sma50 != 0
    mask200 = sma200 != 0

    if mask20.any():
        ax.plot(dates[mask20], sma20[mask20], color=_COLORS["blue"],
                linewidth=1, alpha=0.8, label="SMA 20")
    if mask50.any():
        ax.plot(dates[mask50], sma50[mask50], color=_COLORS["orange"],
                linewidth=1, alpha=0.8, label="SMA 50")
    if mask200.any():
        ax.plot(dates[mask200], sma200[mask200], color=_COLORS["purple"],
                linewidth=1, alpha=0.8, label="SMA 200")

    currency = "원" if ind.market == "KR" else "$"
    ax.set_title(f"{ind.name or ind.ticker} — 주가 · 이동평균 · 볼린저밴드",
                 fontsize=13, fontweight="bold", color=_COLORS["text"], pad=12, loc="left")
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    if ind.market == "KR":
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    else:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.2f}"))

    _format_xaxis(ax, dates)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── 차트 2: RSI ──


def render_rsi_chart(ind: TechnicalIndicators) -> bytes:
    """RSI 14 + 과매수(70)/과매도(30) 라인."""
    dates = _to_dates(ind.dates)
    rsi = np.array(ind.rsi)

    fig, ax = plt.subplots(figsize=(10, 3), dpi=150)
    _apply_style(ax, fig)

    valid = rsi != 0
    if valid.any():
        ax.plot(dates[valid], rsi[valid], color=_COLORS["purple"], linewidth=1.5)

        # 과매수/과매도 영역 채우기
        rsi_valid = rsi[valid]
        dates_valid = dates[valid]
        ax.fill_between(dates_valid, rsi_valid, 70,
                        where=(rsi_valid >= 70), alpha=0.15, color=_COLORS["red"])
        ax.fill_between(dates_valid, rsi_valid, 30,
                        where=(rsi_valid <= 30), alpha=0.15, color=_COLORS["green"])

    # 기준선
    ax.axhline(y=70, color=_COLORS["red"], linewidth=0.8, linestyle="--", alpha=0.7)
    ax.axhline(y=30, color=_COLORS["green"], linewidth=0.8, linestyle="--", alpha=0.7)
    ax.axhline(y=50, color=_COLORS["gray"], linewidth=0.5, linestyle=":", alpha=0.5)

    ax.set_ylim(0, 100)
    ax.set_title("RSI (14)", fontsize=13, fontweight="bold",
                 color=_COLORS["text"], pad=12, loc="left")

    # 현재 RSI 값 표시
    if ind.latest_rsi > 0:
        label = "과매수" if ind.latest_rsi >= 70 else "과매도" if ind.latest_rsi <= 30 else ""
        color = _COLORS["red"] if ind.latest_rsi >= 70 else _COLORS["green"] if ind.latest_rsi <= 30 else _COLORS["sub_text"]
        ax.annotate(f"{ind.latest_rsi:.1f} {label}",
                    xy=(1.01, ind.latest_rsi / 100), xycoords=("axes fraction", "axes fraction"),
                    fontsize=9, fontweight="bold", color=color, va="center")

    _format_xaxis(ax, dates)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── 차트 3: MACD ──


def render_macd_chart(ind: TechnicalIndicators) -> bytes:
    """MACD Line + Signal + Histogram."""
    dates = _to_dates(ind.dates)
    macd = np.array(ind.macd_line)
    signal = np.array(ind.macd_signal)
    hist = np.array(ind.macd_histogram)

    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=150)
    _apply_style(ax, fig)

    # 유효 범위 (EMA가 수렴한 이후)
    valid = (macd != 0) | (signal != 0)
    if valid.any():
        # Histogram (바)
        colors = [_COLORS["red"] if h >= 0 else _COLORS["blue"] for h in hist[valid]]
        ax.bar(dates[valid], hist[valid], color=colors, alpha=0.4, width=1.5)

        # MACD + Signal 라인
        ax.plot(dates[valid], macd[valid], color=_COLORS["blue"],
                linewidth=1.5, label="MACD")
        ax.plot(dates[valid], signal[valid], color=_COLORS["orange"],
                linewidth=1, label="Signal")

    ax.axhline(y=0, color=_COLORS["light_gray"], linewidth=0.8)
    ax.set_title("MACD (12, 26, 9)", fontsize=13, fontweight="bold",
                 color=_COLORS["text"], pad=12, loc="left")
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    _format_xaxis(ax, dates)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── 차트 4: 거래량 ──


def render_volume_chart(ind: TechnicalIndicators) -> bytes:
    """거래량 바 + 20일 SMA."""
    dates = _to_dates(ind.dates)
    volumes = np.array(ind.volumes, dtype=float)
    closes = np.array(ind.closes)
    vol_sma = np.array(ind.volume_sma20)

    fig, ax = plt.subplots(figsize=(10, 3), dpi=150)
    _apply_style(ax, fig)

    # 상승/하락 색상
    colors = []
    for i in range(len(closes)):
        if i == 0:
            colors.append(_COLORS["gray"])
        elif closes[i] >= closes[i - 1]:
            colors.append(_COLORS["red"])
        else:
            colors.append(_COLORS["blue"])

    ax.bar(dates, volumes, color=colors, alpha=0.6, width=1.5)

    # 20일 거래량 SMA
    valid_sma = vol_sma != 0
    if valid_sma.any():
        ax.plot(dates[valid_sma], vol_sma[valid_sma], color=_COLORS["orange"],
                linewidth=1.2, label="20일 평균")
        ax.legend(fontsize=8, frameon=False, loc="upper left")

    ax.set_title("거래량", fontsize=13, fontweight="bold",
                 color=_COLORS["text"], pad=12, loc="left")

    # Y축 포맷 (M/K 단위)
    def _vol_fmt(x, _):
        if x >= 1_000_000:
            return f"{x / 1_000_000:.1f}M"
        if x >= 1_000:
            return f"{x / 1_000:.0f}K"
        return f"{x:.0f}"

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_vol_fmt))
    _format_xaxis(ax, dates)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── 전체 렌더링 ──


def render_all_charts(ind: TechnicalIndicators) -> dict[str, bytes]:
    """4개 차트를 모두 렌더링한다."""
    return {
        "price": render_price_chart(ind),
        "rsi": render_rsi_chart(ind),
        "macd": render_macd_chart(ind),
        "volume": render_volume_chart(ind),
    }
