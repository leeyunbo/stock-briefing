"""시장 지도 프롬프트 테스트 — 프로바이더는 가짜로 대체."""

import json
from datetime import date
from unittest.mock import patch

import pytest

import app.prompts.market_map as mm
from app.collector.naver_research import ResearchReport
from app.prompts.market_map import (
    Change,
    MarketBrief,
    Thread,
    build_market_brief,
    build_user_prompt,
    parse_brief,
    threads_from_state,
    threads_to_state,
)

TODAY = date(2026, 9, 12)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(mm, "_RETRY_SLEEP", 0)


def _report(i: int) -> ResearchReport:
    return ResearchReport(category="시황", title=f"리포트 {i}", broker=f"증권사{i}", date=date(2026, 9, 11),
                          ticker=None, pdf_url=None, read_url=f"https://x/{i}", excerpt=f"본문 {i} " * 30, views=100 - i)


PREV = [
    Thread("oil-rates", "유가발 금리 인상 우려", "어제 status", "up", "2026-09-05"),
    Thread("chips", "반도체 사이클", "어제 status", "flat", "2026-09-05"),
]

RESPONSE = {
    "one_liner": "유가 급등에도 코스피는 반도체 덕에 6.9% 올랐어요.",
    "threads": [
        {"id": "oil-rates", "title": "유가발 금리 인상 우려", "status": "WTI 102달러, 인상 확률 86%예요.", "direction": "up"},
        {"id": "chips", "title": "반도체 사이클", "status": "9월 초 수출 +270%예요.", "direction": "down"},
        {"id": "KRW Strength!!", "title": "원화 강세", "status": "1,336원이에요.", "direction": "flat"},
    ],
    "change": {"title": "PPI 5.4% 서프라이즈", "headline": "8월 생산자물가가 예상보다 높게 나왔어요", "emoji": "🛢️",
               "source": "SK증권", "body": "<p><strong>5.4%</strong>였어요.</p><p>다만 에너지 탓이 커요.</p><p>셋째 문단</p>",
               "report_idx": [0, 99]},
    "concept": {"term": "10년물 국채 금리", "text": "미국 정부가 10년 돈을 빌릴 때 내는 이자예요."},
    "watch": ["9/16(화) FOMC", "9/11(금) CPI", "셋째는 버림"],
}


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses); self.calls = []

    def call(self, system, user):
        self.calls.append((system, user))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ── parse_brief ──

def test_parse_brief_threads_directions_and_since():
    b = parse_brief(RESPONSE, [_report(0)], PREV, TODAY)
    assert isinstance(b, MarketBrief)
    assert [t.id for t in b.threads] == ["oil-rates", "chips", "krw-strength"]
    assert [t.direction for t in b.threads] == ["up", "down", "new"]  # 새 id는 강제로 new
    assert b.threads[0].since == "2026-09-05" and b.threads[2].since == "2026-09-12"


def test_parse_brief_prev_thread_with_new_direction_becomes_flat():
    data = {**RESPONSE, "threads": [{"id": "oil-rates", "title": "t", "status": "s", "direction": "new"},
                                    {"id": "chips", "title": "t2", "status": "s", "direction": "bogus"}]}
    b = parse_brief(data, [], PREV, TODAY)
    assert [t.direction for t in b.threads] == ["flat", "flat"]


def test_parse_brief_change_caps_paragraphs_and_sources():
    b = parse_brief(RESPONSE, [_report(0)], PREV, TODAY)
    assert isinstance(b.change, Change)
    assert b.change.body_html.count("<p>") == 2 and "셋째" not in b.change.body_html
    assert b.change.sources == ["증권사0 · 리포트 0 (9/11)"]  # 99는 범위 밖
    assert b.change.header == "8월 생산자물가가 예상보다 높게 나왔어요 (SK증권)"


def test_parse_brief_change_too_long_keeps_first_paragraph():
    data = json.loads(json.dumps(RESPONSE))
    data["change"]["body"] = "<p>" + "가" * 300 + "</p><p>" + "나" * 300 + "</p>"
    b = parse_brief(data, [], PREV, TODAY)
    assert b.change.body_html.count("<p>") == 1


def test_parse_brief_change_null_and_extras_trimmed():
    data = {**RESPONSE, "change": None}
    b = parse_brief(data, [], PREV, TODAY)
    assert b.change is None
    assert b.watch == ["9/16(화) FOMC", "9/11(금) CPI"]
    assert b.concept.term == "10년물 국채 금리"


def test_parse_brief_change_script_sanitized():
    data = json.loads(json.dumps(RESPONSE))
    data["change"]["body"] = '<p onclick="x">a<script>alert(1)</script></p><p>b</p>'
    b = parse_brief(data, [], PREV, TODAY)
    assert "<script" not in b.change.body_html and "onclick" not in b.change.body_html and "alert" not in b.change.body_html


def test_parse_brief_too_few_threads_returns_none():
    data = {**RESPONSE, "threads": [RESPONSE["threads"][0]]}
    assert parse_brief(data, [], PREV, TODAY) is None


def test_parse_brief_caps_threads_at_four():
    data = {**RESPONSE, "threads": [{"id": f"t{i}", "title": f"t{i}", "status": "s", "direction": "new"} for i in range(6)]}
    assert len(parse_brief(data, [], [], TODAY).threads) == 4


# ── 프롬프트 ──

def test_user_prompt_contains_prev_threads_reports_and_concepts():
    p = build_user_prompt([_report(0)], {"market": "거시 텍스트"}, PREV, ["PER"], TODAY)
    assert "id=oil-rates" in p and "리포트 0" in p and "거시 텍스트" in p and "PER" in p and "2026-09-12" in p


def test_user_prompt_first_run():
    p = build_user_prompt([], {}, [], [], TODAY)
    assert "첫 실행" in p and "리포트 없음" in p


# ── build_market_brief ──

@pytest.mark.asyncio
async def test_build_market_brief_success_and_retry():
    fp = FakeProvider([RuntimeError("claude CLI 에러: "), "```json\n" + json.dumps(RESPONSE, ensure_ascii=False) + "\n```"])
    with patch("app.prompts.market_map.get_provider", return_value=fp):
        b = await build_market_brief({"market": "m"}, [_report(0)], PREV, [], TODAY)
    assert b and len(b.threads) == 3 and len(fp.calls) == 2
    assert "id=oil-rates" in fp.calls[1][1]
    assert "주 1회 재정비" not in fp.calls[1][0]


@pytest.mark.asyncio
async def test_build_market_brief_reset_ignores_prev_and_marks_new():
    fp = FakeProvider([json.dumps(RESPONSE, ensure_ascii=False)])
    with patch("app.prompts.market_map.get_provider", return_value=fp):
        b = await build_market_brief({}, [], PREV, [], TODAY, reset=True)
    assert "주 1회 재정비" in fp.calls[0][0]
    assert "id=oil-rates" not in fp.calls[0][1]
    assert all(t.direction == "new" for t in b.threads)


@pytest.mark.asyncio
async def test_build_market_brief_all_fail_returns_none():
    fp = FakeProvider([RuntimeError("x")] * 3)
    with patch("app.prompts.market_map.get_provider", return_value=fp):
        assert await build_market_brief({}, [], [], [], TODAY) is None


@pytest.mark.asyncio
async def test_build_market_brief_bad_json_returns_none():
    fp = FakeProvider(["이건 JSON이 아니에요"] * 3)
    with patch("app.prompts.market_map.get_provider", return_value=fp):
        assert await build_market_brief({}, [], [], [], TODAY) is None


def test_parse_json_survives_html_in_body():
    """body의 </p> 뒤에 JSON이 이어져도 잘리지 않아야 한다 (strip_code_block 회귀 방지)."""
    raw = "```json\n" + json.dumps(RESPONSE, ensure_ascii=False) + "\n```"
    data = mm._parse_json_object(raw)
    assert data["watch"] == RESPONSE["watch"] and data["concept"]["term"] == "10년물 국채 금리"


# ── 상태 직렬화 ──

def test_state_roundtrip_and_recent_concepts():
    b = parse_brief(RESPONSE, [], PREV, TODAY)
    state = threads_to_state(b, TODAY, ["PER", "10년물 국채 금리", "환율"])
    assert state["updated"] == "2026-09-12"
    assert state["recent_concepts"] == ["10년물 국채 금리", "PER", "환율"]  # 오늘 것 맨 앞, 중복 제거
    threads, concepts = threads_from_state(state)
    assert [t.id for t in threads] == ["oil-rates", "chips", "krw-strength"]
    assert threads[0].since == "2026-09-05"
    assert concepts[0] == "10년물 국채 금리"


def test_threads_from_state_tolerates_garbage():
    assert threads_from_state(None) == ([], [])
    threads, concepts = threads_from_state({"threads": [{"nope": 1}, {"id": "a", "title": "A"}], "recent_concepts": ["x", 3]})
    assert [t.id for t in threads] == ["a"] and concepts == ["x"]
