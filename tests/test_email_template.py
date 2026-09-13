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

from app.prompts.market_map import Change, Concept, MarketBrief, Thread
from app.publishing.email_template import render_daily_brief

_BRIEF = MarketBrief(
    one_liner="유가 급등에도 코스피는 반도체 덕에 6.9% 올랐어요.",
    threads=[
        Thread("oil-rates", "유가발 금리 인상 우려", "WTI 102달러, 인상 확률 86%예요.", "up", "2026-09-05"),
        Thread("chips", "반도체 사이클", "9월 초 수출 +270%예요.", "flat", "2026-09-05"),
        Thread("krw", "원화 강세", "1,336원으로 23개월 최저예요.", "new", "2026-09-12"),
    ],
    change=Change("PPI 5.4% 서프라이즈", "8월 생산자물가가 예상보다 높게 나왔어요", "🛢️", "SK증권",
                  "<p><strong>5.4%</strong>로 예상 5.3%를 웃돌았어요.</p><p>다음 주 CPI가 관문이에요. 다만 에너지 탓이 커요.</p>",
                  ["SK증권 · 매크로 Comment (9/11)"]),
    concept=Concept("10년물 국채 금리", "미국 정부가 10년 돈을 빌릴 때 내는 이자예요. 이게 오르면 주식의 매력이 떨어져요."),
    watch=["9/16(화) FOMC 금리 결정", "9/11(금) 미 8월 CPI"],
)


def test_daily_brief_full():
    subject, html = render_daily_brief(brief_date=date(2026, 9, 12), brief=_BRIEF, run_id="run-1")
    assert subject == "PPI 5.4% 서프라이즈 | 9월 12일 아침 브리핑"
    assert "유가 급등에도 코스피는 반도체 덕에 6.9% 올랐어요." in html
    assert "지금 시장의 큰 줄기" in html
    assert "유가발 금리 인상 우려" in html and "강해짐" in html and "새 줄기" in html and "그대로" in html
    assert "🛢️ 8월 생산자물가가 예상보다 높게 나왔어요 (SK증권)" in html
    assert "<strong>5.4%</strong>로 예상 5.3%를 웃돌았어요." in html
    assert "SK증권 · 매크로 Comment (9/11)" in html
    assert "오늘의 개념" in html and "10년물 국채 금리" in html
    assert "9/16(화) FOMC 금리 결정" in html
    assert "투자 권유가 아니고" in html
    assert "2026년 9월 12일" in html and "run-1" in html
    assert "<html" in html.lower()


def test_daily_brief_without_change():
    b = MarketBrief(one_liner="", threads=_BRIEF.threads, change=None, concept=None, watch=[])
    subject, html = render_daily_brief(brief_date=date(2026, 9, 12), brief=b)
    assert subject == "큰 줄기 그대로 | 9월 12일 아침 브리핑"
    assert "새로 생긴 건 없어요" in html
    assert "📚 오늘의 개념" not in html and "📅 이번 주 지켜볼 것" not in html


def test_daily_brief_none():
    subject, html = render_daily_brief(brief_date=date(2026, 9, 12), brief=None)
    assert subject == "9월 12일 아침 브리핑"
    assert "흐름을 정리하지 못했어요" in html
    assert "🧭 지금 시장의 큰 줄기" not in html
