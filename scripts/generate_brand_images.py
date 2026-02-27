"""브랜드 이미지 생성 — favicon.svg 기반 워드프레스용.

생성 파일:
  static/logo-112x112.png       — 구글 검색 결과 로고
  static/default-og-1200x630.png — 기본 소셜 공유 이미지 (OG)
"""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
_BG = "#1a1a2e"
_ACCENT = "#3182F6"

_ROOT = Path(__file__).resolve().parent.parent
_OUT_DIR = _ROOT / "static"
_THEME_DIR = _ROOT / "wordpress-theme" / "moneydive 13"


def _load_font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size, index=index)
    except OSError:
        return ImageFont.load_default()


def _svg_to_png(svg_path: Path, out_path: Path, width: int, height: int):
    """qlmanage(macOS)로 SVG → PNG 변환."""
    # rsvg-convert가 있으면 사용, 없으면 cairosvg 시도
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(width), "-h", str(height),
             str(svg_path), "-o", str(out_path)],
            check=True, capture_output=True,
        )
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # cairosvg fallback
    import cairosvg
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(out_path),
        output_width=width,
        output_height=height,
    )


def generate_logo():
    """112x112 구글 로고 — favicon.svg를 래스터화."""
    svg = _THEME_DIR / "favicon.svg"
    tmp = _OUT_DIR / "_favicon_raw.png"
    _svg_to_png(svg, tmp, 112, 112)

    img = Image.open(tmp).convert("RGBA")
    tmp.unlink()

    # PNG로 저장
    out = _OUT_DIR / "logo-112x112.png"
    img.save(out, "PNG", optimize=True)
    print(f"  logo: {out} ({img.size[0]}x{img.size[1]})")


def generate_default_og():
    """1200x630 기본 소셜 공유 이미지."""
    W, H = 1200, 630

    img = Image.new("RGBA", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # 파란색 중앙 띠 (기존 default-og.png 스타일)
    band_top = int(H * 0.1)
    band_bottom = int(H * 0.82)
    draw.rectangle([(0, band_top), (W, band_bottom)], fill=_ACCENT)

    # 중앙에 favicon SVG를 큰 사이즈로 래스터화
    icon_size = 260
    svg = _THEME_DIR / "favicon.svg"
    tmp = _OUT_DIR / "_icon_raw.png"
    _svg_to_png(svg, tmp, icon_size, icon_size)

    icon = Image.open(tmp).convert("RGBA")
    tmp.unlink()

    # 흰색 라운드 카드 배경
    card_padding = 36
    card_w = icon_size + card_padding * 2
    card_h = icon_size + card_padding * 2
    card_x = (W - card_w) // 2
    card_y = (band_top + band_bottom - card_h) // 2 - 15

    # 라운드 사각형 카드
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle(
        [(0, 0), (card_w - 1, card_h - 1)],
        radius=32, fill=(255, 255, 255, 255),
    )
    img.paste(card, (card_x, card_y), card)

    # 아이콘을 카드 위에 배치
    icon_x = card_x + card_padding
    icon_y = card_y + card_padding
    img.paste(icon, (icon_x, icon_y), icon)

    # 카드 아래 점 3개 (기존 스타일)
    dot_y = card_y + card_h + 20
    dot_r = 5
    for i in range(3):
        cx = W // 2 + (i - 1) * 20
        draw.ellipse(
            [(cx - dot_r, dot_y - dot_r), (cx + dot_r, dot_y + dot_r)],
            fill=(255, 255, 255, 153),
        )

    out = _OUT_DIR / "default-og-1200x630.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"    og: {out} ({W}x{H})")


if __name__ == "__main__":
    _OUT_DIR.mkdir(exist_ok=True)
    generate_logo()
    generate_default_og()
