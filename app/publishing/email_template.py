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


def render_daily_brief(*, brief_date, deep_dive=None, run_id: str = "") -> tuple[str, str]:
    """개인 아침 브리핑 이메일('월가소식' 형식)을 렌더링한다. (subject, html) 반환.

    deep_dive: app.prompts.deep_dive.DeepDive | None. None이면 주제 없음 안내만.
    """
    date_label = f"{brief_date.month}월 {brief_date.day}일 아침 브리핑"
    topics = list(deep_dive.topics) if deep_dive else []
    toc = " / ".join(t.title for t in topics)
    subject = f"{toc} | {date_label}" if toc else date_label
    template = _env.get_template("email_daily_brief.html")
    html = template.render(
        subject=escape(subject),
        date_label=date_label,
        date_short=f"{brief_date.month}/{brief_date.day}",
        date_full=f"{brief_date.year}년 {brief_date.month}월 {brief_date.day}일",
        topics_headline=escape(toc),
        summary=[str(escape(x)) for x in deep_dive.summary] if deep_dive else [],
        topics=topics,
        run_id=run_id,
    )
    return subject, html
