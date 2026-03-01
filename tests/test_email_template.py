"""이메일 템플릿 테스트."""

from app.publishing.email_template import render_email


def test_render_email_contains_title():
    """render_email이 제목을 포함한 완성된 HTML을 반환한다."""
    result = render_email(
        "2025년 02월 11일 브리핑",
        "오늘 시장 요약입니다.",
        "https://blog.example.com/post/123",
        "국내주식",
    )
    assert "2025년 02월 11일 브리핑" in result
    assert "<html" in result.lower()


def test_render_email_contains_blog_url():
    """render_email이 블로그 링크를 포함한다."""
    result = render_email(
        "테스트 제목",
        "요약 텍스트",
        "https://blog.example.com/post/456",
        "미국주식",
    )
    assert "https://blog.example.com/post/456" in result
    assert "자세히 보기" in result


def test_render_email_contains_category():
    """render_email이 카테고리를 표시한다."""
    result = render_email(
        "테스트 제목",
        "요약",
        "https://example.com",
        "뉴스 딥다이브",
    )
    assert "뉴스 딥다이브" in result
