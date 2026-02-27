"""OG 이미지 자동 생성 모듈.

제목 기반으로 1200×630 OG 표준 사이즈 이미지를 생성한다.
WordPress 대표 이미지(Featured Image)로 사용된다.
"""

import logging
import textwrap
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# 카테고리별 포인트 컬러
_CATEGORY_COLORS: dict[str, str] = {
    "국내주식": "#e74c3c",
    "미국주식": "#3498db",
    "부동산": "#27ae60",
    "뉴스 딥다이브": "#9b59b6",
}

# briefing_type → 카테고리 표시명
CATEGORY_DISPLAY: dict[str, str] = {
    "kospi_briefing": "국내주식",
    "nasdaq_briefing": "미국주식",
    "news_dive": "뉴스 딥다이브",
    "real_estate_briefing": "부동산",
}

_FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
_BG_COLOR = "#1a1a2e"
_WIDTH = 1200
_HEIGHT = 630


def _load_font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    """시스템 한글 폰트를 로드한다."""
    try:
        return ImageFont.truetype(_FONT_PATH, size, index=index)
    except OSError:
        logger.warning("한글 폰트 로드 실패: %s — 기본 폰트 사용", _FONT_PATH)
        return ImageFont.load_default()


def _wrap_title(title: str, max_chars_per_line: int = 20, max_lines: int = 3) -> list[str]:
    """제목을 자동 줄바꿈한다. 긴 제목은 말줄임 처리."""
    lines = textwrap.wrap(title, width=max_chars_per_line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        if len(last) > max_chars_per_line - 1:
            last = last[: max_chars_per_line - 1]
        lines[-1] = last.rstrip() + "…"
    return lines


def generate_og_image(title: str, category: str) -> bytes:
    """OG 이미지를 생성하여 PNG bytes로 반환한다.

    Args:
        title: 포스트 제목
        category: 카테고리 표시명 (국내주식, 미국주식, 부동산, 뉴스 딥다이브)

    Returns:
        PNG 이미지 바이트
    """
    accent = _CATEGORY_COLORS.get(category, "#3498db")
    img = Image.new("RGB", (_WIDTH, _HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 상단 악센트 바
    draw.rectangle([(0, 0), (_WIDTH, 6)], fill=accent)

    # 좌측 악센트 바
    draw.rectangle([(0, 0), (6, _HEIGHT)], fill=accent)

    # 카테고리 뱃지 (상단)
    badge_font = _load_font(28, index=0)
    badge_text = category
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w = badge_bbox[2] - badge_bbox[0]
    badge_h = badge_bbox[3] - badge_bbox[1]
    badge_padding_x = 20
    badge_padding_y = 10
    badge_x = 80
    badge_y = 80

    draw.rounded_rectangle(
        [
            (badge_x, badge_y),
            (badge_x + badge_w + badge_padding_x * 2, badge_y + badge_h + badge_padding_y * 2),
        ],
        radius=8,
        fill=accent,
    )
    draw.text(
        (badge_x + badge_padding_x, badge_y + badge_padding_y),
        badge_text,
        fill="white",
        font=badge_font,
    )

    # 제목 텍스트 (중앙)
    title_font = _load_font(52, index=3)  # index=3: Bold
    lines = _wrap_title(title)
    line_height = 72
    title_start_y = 180

    for i, line in enumerate(lines):
        draw.text(
            (80, title_start_y + i * line_height),
            line,
            fill="white",
            font=title_font,
        )

    # 하단 구분선
    separator_y = _HEIGHT - 100
    draw.rectangle([(80, separator_y), (_WIDTH - 80, separator_y + 1)], fill="#333355")

    # 브랜드 텍스트 (하단)
    brand_font = _load_font(30, index=0)
    draw.text(
        (80, _HEIGHT - 75),
        "머니다이브",
        fill="#888899",
        font=brand_font,
    )

    # PNG bytes 반환
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
