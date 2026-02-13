"""이메일 템플릿 렌더링 — 스프링의 Thymeleaf 서비스 역할.

관심사 분리:
- templates/email_briefing.html → HTML 구조 (디자이너 영역)
- 이 모듈 → 스타일링 + 렌더링 로직 (개발자 영역)
- scheduler.py → 비즈니스 로직만 남음
"""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=False)


def render_email(title: str, content_html: str) -> str:
    """브리핑 HTML을 다크 테마 이메일 템플릿으로 렌더링한다."""
    styled = _style_content_html(content_html)
    template = _env.get_template("email_briefing.html")
    return template.render(title=title, content_html=styled)


def _style_content_html(html: str) -> str:
    """AI가 생성한 HTML에 다크 테마 인라인 스타일을 자동 적용한다."""
    # <h2> → 섹션 헤더 (왼쪽 파란 바 + 흰 볼드)
    html = re.sub(
        r'<h2>(.*?)</h2>',
        r'<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top: 28px; margin-bottom: 14px;">'
        r'<tr><td style="width: 4px; background-color: #3182F6; border-radius: 2px;"></td>'
        r'<td style="padding-left: 12px; font-size: 17px; font-weight: 700; color: #FFFFFF; line-height: 1.4;">\1</td>'
        r'</tr></table>',
        html,
    )
    # <ul> → 리스트 컨테이너
    html = html.replace('<ul>', '<ul style="list-style: none; padding: 0; margin: 0 0 8px 0;">')
    # <li> → 리스트 아이템 (다크 카드)
    html = re.sub(
        r'<li(?:\s[^>]*)?>',
        '<li style="background-color: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; font-size: 14px; line-height: 1.75; color: rgba(255,255,255,0.75);">',
        html,
    )
    # <strong> → 흰색 볼드
    html = html.replace('<strong>', '<strong style="color: #FFFFFF; font-weight: 700;">')
    # <p> → 본문 텍스트
    html = re.sub(
        r'<p(?:\s[^>]*)?>',
        '<p style="font-size: 14px; line-height: 1.75; color: rgba(255,255,255,0.65); margin: 0 0 12px 0;">',
        html,
    )
    return html
