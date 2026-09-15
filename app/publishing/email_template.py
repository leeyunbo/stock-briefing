"""이메일 템플릿 렌더링 — 티저 스타일.

블로그 링크로 유도하는 간결한 이메일을 생성한다.
전체 본문은 블로그에서 확인하도록 CTA 버튼을 포함한다.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import escape

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=False)


def render_email(title: str, excerpt: str, blog_url: str, category: str = "") -> str:
    """티저 스타일 이메일을 렌더링한다."""
    template = _env.get_template("email_briefing.html")
    return template.render(
        title=title,
        excerpt=excerpt,
        blog_url=blog_url,
        category=category,
    )


_DIR_ICON = {"up": "↑", "flat": "→", "down": "↓", "new": "✦"}
_DIR_LABEL = {"up": "강해짐", "flat": "그대로", "down": "약해짐", "new": "새 줄기"}
_DIR_COLOR = {"up": "#E8503A", "flat": "#8B95A1", "down": "#3182F6", "new": "#00A86B"}


def render_daily_brief(*, brief_date, brief=None, run_id: str = "") -> tuple[str, str]:
    """시장 지도 아침 브리핑 이메일을 렌더링한다. (subject, html) 반환.

    brief: app.prompts.market_map.MarketBrief | None. None이면 안내 문구만.
    """
    date_label = f"{brief_date.month}월 {brief_date.day}일 아침 브리핑"
    if brief and brief.change:
        subject = f"{brief.change.title} | {date_label}"
    elif brief:
        subject = f"큰 줄기 그대로 | {date_label}"
    else:
        subject = date_label
    template = _env.get_template("email_daily_brief.html")
    html = template.render(
        subject=escape(subject),
        title=escape(subject),
        date_full=f"{brief_date.year}년 {brief_date.month}월 {brief_date.day}일",
        brief=brief,
        dir_icon=_DIR_ICON,
        dir_label=_DIR_LABEL,
        dir_color=_DIR_COLOR,
        run_id=run_id,
    )
    return subject, html
