"""딥다이브 프롬프트 테스트 — 프로바이더는 가짜로 대체."""

from datetime import date
from unittest.mock import patch

import pytest

import app.prompts.deep_dive as dd_mod
from app.collector.naver_research import ResearchReport
from app.prompts.deep_dive import (
    DeepDive,
    DeepDiveTopic,
    build_deep_dive,
    sanitize_html,
    select_topics,
    write_topic,
)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(dd_mod, "_RETRY_SLEEP", 0)


def _report(i: int, category: str = "시황") -> ResearchReport:
    return ResearchReport(
        category=category, title=f"리포트 {i}", broker=f"증권사{i}", date=date(2026, 9, 9),
        ticker=None, pdf_url=None, read_url=f"https://x/{i}", excerpt=f"본문 {i} " * 20, views=100 - i,
    )


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, system, user):
        self.calls.append((system, user))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


SELECT_JSON = """```json
[
 {"title": "금리, 내리는 게 아니라 올린다?", "headline": "연준이 금리를 올릴 수도 있어요", "emoji": "🇺🇸", "source": "신한투자증권", "why": "거시", "report_idx": [0, 1], "research_keys": ["market"]},
 {"title": "7천피 공방의 이유", "headline": "코스피가 7,000선에서 밀린 이유예요", "emoji": "🇰🇷", "source": "", "why": "한국", "report_idx": [2], "research_keys": ["themes"]},
 {"title": "셋째", "headline": "셋째", "emoji": "3️⃣", "source": "", "why": "초과", "report_idx": [], "research_keys": []}
]
```"""

BODY_HTML = ("<p><strong>무슨 일이에요?</strong> 금리가 <strong>4.85%</strong>까지 올랐어요.</p>"
             "<p><strong>왜 중요해요?</strong> 금리가 오르면 성장주가 불리해요.</p>"
             "<p><strong>그래서요?</strong> CPI를 보면 돼요. 다만 반반이에요.</p>")


# ── sanitize ──

def test_sanitize_keeps_whitelist_and_drops_script():
    dirty = '<p onclick="x()">a <script>alert(1)</script><b>b</b> <strong>c</strong> <em>d</em></p><ul><li>e</li></ul><div>f</div>'
    out = sanitize_html(dirty)
    assert "<script" not in out and "onclick" not in out and "<div" not in out and "<b>" not in out
    assert "<ul>" not in out and "<li>" not in out  # 불릿은 이 형식에서 미허용
    assert "<strong>c</strong>" in out and "<em>d</em>" in out
    assert "alert(1)" not in out
    assert "e" in out and "f" in out  # 태그는 벗기고 텍스트는 유지


# ── select_topics ──

def test_select_topics_parses_and_caps_at_two():
    fp = FakeProvider([SELECT_JSON])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        sel = select_topics([_report(i) for i in range(3)], {"market": "거시", "themes": "테마"})
    assert len(sel) == 2
    assert sel[0]["title"] == "금리, 내리는 게 아니라 올린다?"
    assert sel[0]["headline"] == "연준이 금리를 올릴 수도 있어요"
    assert sel[0]["source"] == "신한투자증권"
    assert sel[0]["report_idx"] == [0, 1]
    assert "리포트 0" in fp.calls[0][1]
    assert "종목 추천" in fp.calls[0][0]  # 거시 전용 프롬프트


def test_select_topics_title_falls_back_to_headline():
    fp = FakeProvider(['[{"headline":"h1","emoji":"x","report_idx":[],"research_keys":[]},'
                       '{"title":"t2","emoji":"y","report_idx":[],"research_keys":[]}]'])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        sel = select_topics([], {})
    assert sel[0]["title"] == "h1" and sel[0]["headline"] == "h1"
    assert sel[1]["title"] == "t2" and sel[1]["headline"] == "t2"


def test_select_topics_drops_out_of_range_idx():
    fp = FakeProvider(['[{"headline":"h","emoji":"x","why":"w","report_idx":[0, 99],"research_keys":["nope"]},'
                       '{"headline":"h2","emoji":"y","why":"w","report_idx":[],"research_keys":[]}]'])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        sel = select_topics([_report(0)], {"market": "m"})
    assert sel[0]["report_idx"] == [0]
    assert sel[0]["research_keys"] == []


def test_select_topics_single_topic_is_allowed():
    fp = FakeProvider(['[{"headline":"only","emoji":"x","why":"w","report_idx":[],"research_keys":[]}]'])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert len(select_topics([_report(0)], {})) == 1


def test_select_topics_empty_array_returns_empty():
    fp = FakeProvider(["[]"])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert select_topics([_report(0)], {}) == []


def test_select_topics_bad_json_returns_empty():
    fp = FakeProvider(["이건 JSON이 아니에요"])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert select_topics([_report(0)], {}) == []


def test_select_topics_retries_transient_error_then_succeeds():
    fp = FakeProvider([RuntimeError("claude CLI 에러: "), "", SELECT_JSON])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        sel = select_topics([_report(i) for i in range(3)], {"market": "m"})
    assert len(sel) == 2 and len(fp.calls) == 3


# ── write_topic ──

_SEL = {"title": "t", "headline": "h", "emoji": "🇰🇷", "source": "BofA", "why": "w",
        "report_idx": [0, 1], "research_keys": ["market"]}


def test_topic_sections_split_label_and_text():
    t = DeepDiveTopic("t", "h", "x", "", BODY_HTML)
    secs = t.sections
    assert [s[0] for s in secs] == ["무슨 일이에요?", "왜 중요해요?", "그래서요?"]
    assert secs[0][1] == "금리가 <strong>4.85%</strong>까지 올랐어요."
    assert secs[2][1].startswith("CPI를 보면 돼요.")


def test_topic_sections_without_label():
    t = DeepDiveTopic("t", "h", "x", "", "<p>라벨 없음</p><p><em>강조</em> 있음</p>")
    assert t.sections == [("", "라벨 없음"), ("", "<em>강조</em> 있음")]


def test_write_topic_builds_topic_with_sources_and_header():
    fp = FakeProvider([BODY_HTML])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "거시 리서치"})
    assert isinstance(t, DeepDiveTopic)
    assert t.title == "t" and t.headline == "h" and t.emoji == "🇰🇷"
    assert t.header == "h (BofA)"
    assert t.body_html == BODY_HTML
    assert t.sources == ["증권사0 · 리포트 0 (9/9)", "증권사1 · 리포트 1 (9/9)"]
    assert "본문 0" in fp.calls[0][1] and "거시 리서치" in fp.calls[0][1]
    assert len(fp.calls) == 1  # 길이 안 넘으면 압축 호출 없음


def test_write_topic_caps_sources_at_three():
    fp = FakeProvider([BODY_HTML])
    sel = {**_SEL, "report_idx": [0, 1, 2, 3, 4]}
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(sel, [_report(i) for i in range(5)], {"market": "m"})
    assert len(t.sources) == 3 and t.sources[0] == "증권사0 · 리포트 0 (9/9)"


def test_write_topic_header_without_source():
    fp = FakeProvider([BODY_HTML])
    sel = {**_SEL, "source": ""}
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(sel, [_report(0), _report(1)], {"market": "m"})
    assert t.header == "h"


def test_write_topic_compresses_when_too_long():
    long_body = "<p>" + "가" * 300 + "</p><p>" + "나" * 300 + "</p><p>셋째</p><p>넷째</p>"
    short = "<p>짧게</p><p>둘</p><p>셋</p>"
    fp = FakeProvider([long_body, short])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "m"})
    assert t.body_html == short
    assert len(fp.calls) == 2
    assert "압축" in fp.calls[1][0]


def test_write_topic_compress_failure_truncates_to_three_paragraphs():
    long_body = "<p>" + "가" * 300 + "</p><p>" + "나" * 300 + "</p><p>셋째</p><p>넷째</p>"
    fp = FakeProvider([long_body, RuntimeError("x"), RuntimeError("x"), RuntimeError("x")])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "m"})
    assert t.body_html.count("<p>") == 3 and "넷째" not in t.body_html


def test_write_topic_wraps_plain_text_in_paragraph():
    fp = FakeProvider(["태그 없는 본문"])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "m"})
    assert t.body_html == "<p>태그 없는 본문</p>"


def test_write_topic_provider_error_returns_none():
    fp = FakeProvider([RuntimeError("boom")] * 3)
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert write_topic({**_SEL, "report_idx": [], "research_keys": []}, [], {}) is None


# ── build_deep_dive ──
# write_topic은 병렬 실행이라 호출 순서가 비결정적 → 프롬프트 내용으로 응답을 라우팅한다.

class RoutedProvider:
    def __init__(self, select, writes: dict, summary):
        self.select, self.writes, self.summary = select, writes, summary

    def _pick(self, user):
        if "[리포트 목록]" in user:
            return self.select
        if "[전체 요약]" in user:
            return self.summary
        for key, resp in self.writes.items():
            if key in user:
                return resp
        raise AssertionError("라우팅 실패: " + user[:80])

    def call(self, system, user):
        r = self._pick(user)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.mark.asyncio
async def test_build_deep_dive_partial_failure_keeps_others():
    fp = RoutedProvider(
        SELECT_JSON,
        {"연준이 금리를": RuntimeError("boom"), "7,000선": BODY_HTML},
        '"오늘 시장은 금리 4.85%가 눌렀어요."\n- 둘째 줄은 버려요',
    )
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m", "themes": "t"}, [_report(i) for i in range(3)])
    assert isinstance(dd, DeepDive)
    assert [t.title for t in dd.topics] == ["7천피 공방의 이유"]
    assert dd.summary == ["오늘 시장은 금리 4.85%가 눌렀어요."]  # 한 줄만, 따옴표 제거


@pytest.mark.asyncio
async def test_build_deep_dive_select_fails_returns_none():
    fp = RoutedProvider(RuntimeError("boom"), {}, "")
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert await build_deep_dive({}, []) is None


@pytest.mark.asyncio
async def test_build_deep_dive_all_writes_fail_returns_none():
    fp = RoutedProvider(SELECT_JSON, {"연준이 금리를": RuntimeError("a"), "7,000선": RuntimeError("b")}, "")
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert await build_deep_dive({"market": "m"}, [_report(i) for i in range(3)]) is None


@pytest.mark.asyncio
async def test_build_deep_dive_summary_failure_gives_empty_summary():
    fp = RoutedProvider(SELECT_JSON, {"연준이 금리를": BODY_HTML, "7,000선": BODY_HTML}, RuntimeError("x"))
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m"}, [_report(i) for i in range(3)])
    assert dd and len(dd.topics) == 2 and dd.summary == []


@pytest.mark.asyncio
async def test_build_deep_dive_works_without_reports():
    fp = RoutedProvider(
        '[{"headline":"a","emoji":"x","report_idx":[],"research_keys":["market"]},'
        '{"headline":"b","emoji":"y","report_idx":[],"research_keys":["themes"]}]',
        {"[주제] a": BODY_HTML, "[주제] b": BODY_HTML},
        "요약 한 줄이에요.",
    )
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m", "themes": "t"}, [])
    assert dd and len(dd.topics) == 2 and dd.topics[0].sources == ["웹 리서치"]
    assert dd.summary == ["요약 한 줄이에요."]
