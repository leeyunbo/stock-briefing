"""이메일 템플릿 렌더링 — 티저 스타일.

블로그 링크로 유도하는 간결한 이메일을 생성한다.
전체 본문은 블로그에서 확인하도록 CTA 버튼을 포함한다.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

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
