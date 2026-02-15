"""이메일 템플릿 테스트."""

from app.email_template import _style_content_html, render_email


def test_style_content_html_adds_h2_style():
    """<h2> 태그에 인라인 스타일이 추가된다."""
    html = "<h2>제목</h2>"
    styled = _style_content_html(html)
    assert "style=" in styled
    assert "제목" in styled


def test_style_content_html_adds_li_style():
    """<li> 태그에 인라인 스타일이 추가된다."""
    html = "<li>항목</li>"
    styled = _style_content_html(html)
    assert "style=" in styled


def test_render_email_contains_title():
    """render_email이 제목을 포함한 완성된 HTML을 반환한다."""
    result = render_email("2025년 02월 11일 브리핑", "<h2>시장</h2>")
    assert "2025년 02월 11일 브리핑" in result
    assert "<html" in result.lower()
