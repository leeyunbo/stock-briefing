"""AI 트레이싱 테스트."""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AiTrace
from app.tracing import TracingProvider, generate_run_id, _save_trace_sync
from main import app

from tests.db_setup import TestSession, engine as test_engine

# 동기 엔진 (TracingProvider 단위 테스트용)
test_sync_engine = create_engine("sqlite://", echo=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Base.metadata.create_all(test_sync_engine)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    Base.metadata.drop_all(test_sync_engine)


# ── TracingProvider 단위 테스트 ──


def test_tracing_provider_records_success(monkeypatch):
    """성공 호출 시 트레이스가 run_id와 함께 저장된다."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = "AI 응답입니다"
    fake_provider.last_usage = {"input_tokens": 100, "output_tokens": 50}

    monkeypatch.setattr("app.tracing.sync_engine", test_sync_engine)

    tp = TracingProvider(fake_provider, "claude", "claude-sonnet", "kospi", "summarize", "run123")
    result = tp.call("시스템 프롬프트", "유저 프롬프트")

    assert result == "AI 응답입니다"
    fake_provider.call.assert_called_once_with("시스템 프롬프트", "유저 프롬프트")

    with Session(test_sync_engine) as session:
        traces = session.execute(select(AiTrace)).scalars().all()
        assert len(traces) == 1
        t = traces[0]
        assert t.run_id == "run123"
        assert t.pipeline == "kospi"
        assert t.stage == "summarize"
        assert t.success is True
        assert t.input_tokens == 100
        assert t.output_tokens == 50


def test_tracing_provider_records_failure(monkeypatch):
    """실패 호출 시에도 트레이스가 저장되고 예외가 다시 발생한다."""
    fake_provider = MagicMock()
    fake_provider.call.side_effect = RuntimeError("API 에러")
    fake_provider.last_usage = None

    monkeypatch.setattr("app.tracing.sync_engine", test_sync_engine)

    tp = TracingProvider(fake_provider, "claude", "claude-sonnet", "nasdaq", "summarize", "run456")

    with pytest.raises(RuntimeError, match="API 에러"):
        tp.call("sys", "usr")

    with Session(test_sync_engine) as session:
        traces = session.execute(select(AiTrace)).scalars().all()
        assert len(traces) == 1
        t = traces[0]
        assert t.run_id == "run456"
        assert t.success is False
        assert "API 에러" in t.error_message


def test_tracing_provider_no_usage(monkeypatch):
    """last_usage가 없어도 정상 저장된다 (CLI provider)."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = "응답"
    del fake_provider.last_usage

    monkeypatch.setattr("app.tracing.sync_engine", test_sync_engine)

    tp = TracingProvider(fake_provider, "claude-cli", "claude-cli", "news_dive", "analyze", "run789")
    result = tp.call("sys", "usr")

    assert result == "응답"

    with Session(test_sync_engine) as session:
        traces = session.execute(select(AiTrace)).scalars().all()
        assert len(traces) == 1
        t = traces[0]
        assert t.run_id == "run789"
        assert t.input_tokens is None
        assert t.output_tokens is None


def test_save_trace_sync_failure_does_not_raise(monkeypatch):
    """DB 저장 실패 시 예외가 삼켜진다 (파이프라인 보호)."""
    bad_engine = create_engine("sqlite:///nonexistent/path/db.sqlite", echo=False)
    monkeypatch.setattr("app.tracing.sync_engine", bad_engine)

    _save_trace_sync(
        run_id="test",
        pipeline="test",
        stage="test",
        provider_name="test",
        model_name="test",
        system_prompt="s",
        user_prompt="u",
        response="r",
        latency_ms=0,
        input_tokens=None,
        output_tokens=None,
        success=True,
        error_message=None,
    )


def test_generate_run_id():
    """run_id가 12자 hex 문자열로 생성된다."""
    rid = generate_run_id()
    assert len(rid) == 12
    int(rid, 16)  # hex 검증

    # 유니크 확인
    assert generate_run_id() != generate_run_id()


# ── 라우트 테스트 ──


@pytest.mark.asyncio
async def test_traces_list_empty():
    """트레이스가 없을 때 목록 페이지가 정상 렌더링된다."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces")

    assert resp.status_code == 200
    assert "AI Traces" in resp.text
    assert "아직 AI 호출 기록이 없습니다" in resp.text


@pytest.mark.asyncio
async def test_traces_list_groups_by_run():
    """같은 run_id의 트레이스가 하나의 행으로 그룹핑된다."""
    async with TestSession() as session:
        session.add(AiTrace(
            run_id="aabbccddee11", pipeline="news_dive", stage="analyze_news",
            provider_name="claude-cli", model_name="claude-cli",
            system_prompt="s1", user_prompt="u1", response="r1",
            latency_ms=5000, success=True,
        ))
        session.add(AiTrace(
            run_id="aabbccddee11", pipeline="news_dive", stage="generate_report",
            provider_name="claude-cli", model_name="claude-cli",
            system_prompt="s2", user_prompt="u2", response="r2",
            latency_ms=8000, success=True,
        ))
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces")

    assert resp.status_code == 200
    assert "1건의 실행" in resp.text
    assert "2단계" in resp.text


@pytest.mark.asyncio
async def test_traces_filter_by_pipeline():
    """파이프라인 필터가 동작한다."""
    async with TestSession() as session:
        session.add(AiTrace(
            run_id="run_kospi_1", pipeline="kospi", stage="summarize",
            provider_name="claude", model_name="m", system_prompt="s",
            user_prompt="u", response="r", latency_ms=100, success=True,
        ))
        session.add(AiTrace(
            run_id="run_nasdaq_1", pipeline="nasdaq", stage="summarize",
            provider_name="claude", model_name="m", system_prompt="s",
            user_prompt="u", response="r", latency_ms=200, success=True,
        ))
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces?pipeline=kospi")

    assert resp.status_code == 200
    assert "1건의 실행" in resp.text


@pytest.mark.asyncio
async def test_run_detail_shows_flow():
    """run 상세 페이지가 모든 단계를 순서대로 보여준다."""
    async with TestSession() as session:
        session.add(AiTrace(
            run_id="flow_test_123", pipeline="news_dive", stage="analyze_news",
            provider_name="claude-cli", model_name="claude-cli",
            system_prompt="분석 시스템 프롬프트", user_prompt="분석 유저 프롬프트",
            response='{"stories":[]}', latency_ms=5000, success=True,
        ))
        session.add(AiTrace(
            run_id="flow_test_123", pipeline="news_dive", stage="generate_report",
            provider_name="claude-cli", model_name="claude-cli",
            system_prompt="리포트 시스템 프롬프트", user_prompt="리포트 유저 프롬프트",
            response="<h2>리포트</h2>", latency_ms=8000, success=True,
        ))
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces/run/flow_test_123")

    assert resp.status_code == 200
    assert "뉴스 딥다이브" in resp.text
    assert "analyze_news" in resp.text
    assert "generate_report" in resp.text
    assert "분석 시스템 프롬프트" in resp.text
    assert "리포트 유저 프롬프트" in resp.text
    assert "13.0s" in resp.text  # 총 소요시간


@pytest.mark.asyncio
async def test_run_detail_not_found():
    """존재하지 않는 run_id → 404."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces/run/nonexistent")

    assert resp.status_code == 404
