"""OG 이미지 자동 생성 모듈.

제목 기반으로 1200×630 OG 표준 사이즈 이미지를 생성한다.
WordPress 대표 이미지(Featured Image)로 사용된다.
"""

import logging
import textwrap
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.config import get_settings
from app.core.models import BriefingType

logger = logging.getLogger(__name__)

# 카테고리별 포인트 컬러 (메인 + 서브)
_CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "국내주식":     ("#E03147", "#FF6B7A"),
    "미국주식":     ("#2563EB", "#60A5FA"),
    "부동산":       ("#059669", "#34D399"),
    "이슈 딥다이브": ("#D97706", "#FCD34D"),
    "주식 딥다이브": ("#0891B2", "#38BDF8"),
    "머니 딥다이브": ("#16A34A", "#4ADE80"),
    "경제 상식":    ("#B45309", "#FDE68A"),
}

# BriefingType → 카테고리 표시명
CATEGORY_DISPLAY: dict[str, str] = {
    BriefingType.KOSPI:          "국내주식",
    BriefingType.NASDAQ:         "미국주식",
    BriefingType.ISSUE_DIVE:     "이슈 딥다이브",
    BriefingType.REAL_ESTATE:    "부동산",
    BriefingType.STOCK_DEEP_DIVE: "주식 딥다이브",
    BriefingType.SEO_CONTENT:    "머니 딥다이브",
    BriefingType.ECONOMY_CONTENT: "경제 상식",
}

_WIDTH  = 1200
_HEIGHT = 630


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))


def _load_font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    font_path = get_settings().og_font_path
    try:
        return ImageFont.truetype(font_path, size, index=index)
    except OSError:
        logger.warning("한글 폰트 로드 실패: %s — 기본 폰트 사용", font_path)
        return ImageFont.load_default()


def _wrap_title(title: str, max_chars: int = 18, max_lines: int = 3) -> list[str]:
    lines = textwrap.wrap(title, width=max_chars)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        if len(last) > max_chars - 1:
            last = last[:max_chars - 1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _draw_gradient_bg(img: Image.Image, color1: str, color2: str) -> None:
    """좌상단 → 우하단 그라디언트 배경."""
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = _hex("#0F172A")  # 베이스: 슬레이트 950
    r2, g2, b2 = _hex("#1E293B")  # 포인트: 슬레이트 800

    for y in range(_HEIGHT):
        t = y / _HEIGHT
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))


def _draw_deco_circles(img: Image.Image, accent: str) -> None:
    """우측 하단 + 좌측 상단에 장식용 원 레이어."""
    ar, ag, ab = _hex(accent)
    overlay = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # 우측 하단 큰 원
    d.ellipse([(820, 320), (1350, 850)], outline=(ar, ag, ab, 40), width=80)
    d.ellipse([(920, 380), (1280, 740)], outline=(ar, ag, ab, 25), width=40)
    d.ellipse([(1000, 440), (1230, 670)], outline=(ar, ag, ab, 15), width=20)

    # 좌측 상단 작은 원
    d.ellipse([(-120, -120), (180, 180)], outline=(ar, ag, ab, 20), width=40)

    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def _draw_dot_grid(img: Image.Image, accent: str) -> None:
    """우측 영역 점 그리드 패턴."""
    ar, ag, ab = _hex(accent)
    overlay = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    spacing = 36
    for x in range(700, _WIDTH, spacing):
        for y in range(0, _HEIGHT, spacing):
            d.ellipse([(x-2, y-2), (x+2, y+2)], fill=(ar, ag, ab, 35))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def generate_og_image(title: str, category: str) -> bytes:
    """OG 이미지를 생성하여 PNG bytes로 반환한다."""
    accent_main, accent_light = _CATEGORY_COLORS.get(category, ("#2563EB", "#60A5FA"))

    # ── 배경 ──
    img = Image.new("RGB", (_WIDTH, _HEIGHT), "#0F172A")
    _draw_gradient_bg(img, accent_main, accent_light)
    _draw_dot_grid(img, accent_light)
    _draw_deco_circles(img, accent_main)

    draw = ImageDraw.Draw(img)

    # ── 좌측 상단 컬러 바 ──
    am = _hex(accent_main)
    al = _hex(accent_light)
    bar_h = 5
    for x in range(0, _WIDTH):
        t = x / _WIDTH
        r = int(am[0] + (al[0] - am[0]) * t)
        g = int(am[1] + (al[1] - am[1]) * t)
        b = int(am[2] + (al[2] - am[2]) * t)
        draw.line([(x, 0), (x, bar_h - 1)], fill=(r, g, b))

    # ── 카테고리 뱃지 ──
    badge_font = _load_font(26)
    badge_text = f"  {category}  "
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    bx, by = 72, 80
    draw.rounded_rectangle(
        [(bx, by), (bx + bw + 8, by + bh + 14)],
        radius=6,
        fill=tuple(list(_hex(accent_main)) + [220]),
    )
    draw.text((bx + 4, by + 7), badge_text, fill="white", font=badge_font)

    # ── 제목 ──
    title_font = _load_font(58, index=3)
    lines = _wrap_title(title)
    line_h = 80
    title_y = 185

    # 제목 그림자 효과
    for i, line in enumerate(lines):
        draw.text((82, title_y + i * line_h + 2), line, fill=(0, 0, 0, 80), font=title_font)

    for i, line in enumerate(lines):
        draw.text((80, title_y + i * line_h), line, fill="white", font=title_font)

    # ── 하단 구분선 + 브랜딩 ──
    sep_y = _HEIGHT - 95
    # 그라디언트 구분선
    for x in range(72, 72 + 200):
        t = (x - 72) / 200
        r = int(am[0] + (al[0] - am[0]) * t)
        g = int(am[1] + (al[1] - am[1]) * t)
        b = int(am[2] + (al[2] - am[2]) * t)
        draw.line([(x, sep_y), (x, sep_y + 2)], fill=(r, g, b, 180))

    brand_font = _load_font(28)
    draw.text((72, sep_y + 14), "머니다이브", fill="#94A3B8", font=brand_font)

    # 우측 하단 URL
    url_font = _load_font(22)
    url_text = "dailymoneydive.com"
    url_bbox = draw.textbbox((0, 0), url_text, font=url_font)
    url_w = url_bbox[2] - url_bbox[0]
    draw.text((_WIDTH - url_w - 72, sep_y + 18), url_text, fill="#475569", font=url_font)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
