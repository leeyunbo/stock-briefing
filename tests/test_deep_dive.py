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
 {"title": "버블 경보가 풀린 코스피?", "headline": "코스피, 버블 경보가 풀렸습니다", "emoji": "🇰🇷", "source": "BofA", "why": "밸류", "report_idx": [0, 1], "research_keys": ["market"]},
 {"title": "격차가 커진 미국 중간선거", "headline": "미국 중간선거, 격차가 커졌습니다", "emoji": "🇺🇸", "source": "", "why": "정치", "report_idx": [2], "research_keys": []},
 {"title": "양산 문턱에 선 CPO 장비", "headline": "CPO 장비, 양산 문턱에 섰습니다", "emoji": "🔬", "source": "키움", "why": "테마", "report_idx": [], "research_keys": ["themes"]},
 {"title": "네번째", "headline": "네번째", "emoji": "4️⃣", "source": "", "why": "초과", "report_idx": [], "research_keys": []}
]
```"""

BODY_HTML = "<p><strong>0.52</strong>까지 내려왔습니다 (BofA).</p><p>결론입니다. 다만 단서가 있습니다.</p>"


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

def test_select_topics_parses_and_caps_at_three():
    fp = FakeProvider([SELECT_JSON])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        sel = select_topics([_report(i) for i in range(3)], {"market": "거시", "themes": "테마"})
    assert len(sel) == 3
    assert sel[0]["title"] == "버블 경보가 풀린 코스피?"
    assert sel[0]["headline"] == "코스피, 버블 경보가 풀렸습니다"
    assert sel[0]["source"] == "BofA"
    assert sel[0]["report_idx"] == [0, 1]
    assert "리포트 0" in fp.calls[0][1]


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


def test_select_topics_fewer_than_two_returns_empty():
    fp = FakeProvider(['[{"headline":"only","emoji":"x","why":"w","report_idx":[],"research_keys":[]}]'])
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
    assert len(sel) == 3 and len(fp.calls) == 3


# ── write_topic ──

_SEL = {"title": "t", "headline": "h", "emoji": "🇰🇷", "source": "BofA", "why": "w",
        "report_idx": [0, 1], "research_keys": ["market"]}


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
    long_body = "<p>" + "가" * 400 + "</p><p>" + "나" * 400 + "</p><p>셋째</p>"
    short = "<p>짧게</p><p>둘</p>"
    fp = FakeProvider([long_body, short])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "m"})
    assert t.body_html == short
    assert len(fp.calls) == 2
    assert "압축" in fp.calls[1][0]


def test_write_topic_compress_failure_truncates_to_two_paragraphs():
    long_body = "<p>" + "가" * 400 + "</p><p>" + "나" * 400 + "</p><p>셋째</p>"
    fp = FakeProvider([long_body, RuntimeError("x"), RuntimeError("x"), RuntimeError("x")])
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        t = write_topic(_SEL, [_report(0), _report(1)], {"market": "m"})
    assert t.body_html.count("<p>") == 2 and "셋째" not in t.body_html


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
        {"버블 경보": BODY_HTML, "중간선거": RuntimeError("boom"), "CPO": BODY_HTML},
        "- 요약 하나\n- 요약 둘\n- 요약 셋",
    )
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m", "themes": "t"}, [_report(i) for i in range(3)])
    assert isinstance(dd, DeepDive)
    assert [t.title for t in dd.topics] == ["버블 경보가 풀린 코스피?", "양산 문턱에 선 CPO 장비"]
    assert dd.summary == ["요약 하나", "요약 둘"]  # 주제 수만큼만


@pytest.mark.asyncio
async def test_build_deep_dive_select_fails_returns_none():
    fp = RoutedProvider(RuntimeError("boom"), {}, "")
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert await build_deep_dive({}, []) is None


@pytest.mark.asyncio
async def test_build_deep_dive_all_writes_fail_returns_none():
    fp = RoutedProvider(SELECT_JSON, {"버블": RuntimeError("a"), "중간선거": RuntimeError("b"), "CPO": RuntimeError("c")}, "")
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        assert await build_deep_dive({"market": "m"}, [_report(i) for i in range(3)]) is None


@pytest.mark.asyncio
async def test_build_deep_dive_summary_failure_gives_empty_summary():
    fp = RoutedProvider(SELECT_JSON, {"버블": BODY_HTML, "중간선거": BODY_HTML, "CPO": BODY_HTML}, RuntimeError("x"))
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m"}, [_report(i) for i in range(3)])
    assert dd and len(dd.topics) == 3 and dd.summary == []


@pytest.mark.asyncio
async def test_build_deep_dive_works_without_reports():
    fp = RoutedProvider(
        '[{"headline":"a","emoji":"x","report_idx":[],"research_keys":["market"]},'
        '{"headline":"b","emoji":"y","report_idx":[],"research_keys":["themes"]}]',
        {"[주제] a": BODY_HTML, "[주제] b": BODY_HTML},
        "- 요약",
    )
    with patch("app.prompts.deep_dive.get_provider", return_value=fp):
        dd = await build_deep_dive({"market": "m", "themes": "t"}, [])
    assert dd and len(dd.topics) == 2 and dd.topics[0].sources == ["웹 리서치"]
