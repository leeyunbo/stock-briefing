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


# ── render_daily_brief ──

from datetime import date

from app.prompts.deep_dive import DeepDive, DeepDiveTopic
from app.publishing.email_template import render_daily_brief

_DD = DeepDive(
    summary=["코스피 선행 PER 6.2배로 백분위 1", "유가 WTI 90달러대"],
    topics=[
        DeepDiveTopic("버블 경보가 풀린 코스피?", "🇰🇷", "<p><strong>BofA</strong> 지표 0.52</p>", ["신한 · 마켓레이더 (9/9)"]),
        DeepDiveTopic("양산 문턱에 선 CPO 장비", "🔬", "<p>본문</p>", ["웹 리서치"]),
    ],
)


def test_daily_brief_with_deep_dive():
    subject, html = render_daily_brief(
        brief_date=date(2026, 9, 10),
        overview_html="<p>🎯 <strong>오늘의 큰 그림</strong></p>",
        opinions_html="<p>🐂 <strong>낙관론자</strong></p>",
        deep_dive=_DD,
        run_id="run-1",
    )
    assert subject == "버블 경보가 풀린 코스피? / 양산 문턱에 선 CPO 장비 | 9월 10일 아침 브리핑"
    assert "전체 요약" in html
    assert "코스피 선행 PER 6.2배로 백분위 1" in html
    assert "버블 경보가 풀린 코스피?" in html and "양산 문턱에 선 CPO 장비" in html
    assert "<strong>BofA</strong> 지표 0.52" in html
    assert "신한 · 마켓레이더 (9/9)" in html
    assert "투자 권유" in html
    assert "오늘의 큰 그림" in html and "낙관론자" in html
    assert "run-1" in html
    assert "<html" in html.lower()


def test_daily_brief_without_deep_dive():
    subject, html = render_daily_brief(
        brief_date=date(2026, 9, 10),
        overview_html="<p>대시보드</p>",
        opinions_html="<p>시선</p>",
        deep_dive=None,
    )
    assert subject == "9월 10일 아침 브리핑"
    assert "전체 요약" not in html
    assert "대시보드" in html and "시선" in html


def test_daily_brief_empty_summary_hides_summary_box():
    dd = DeepDive(summary=[], topics=_DD.topics)
    _, html = render_daily_brief(brief_date=date(2026, 9, 10), overview_html="", opinions_html="", deep_dive=dd)
    assert "전체 요약" not in html
    assert "버블 경보가 풀린 코스피?" in html
