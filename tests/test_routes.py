"""라우트 테스트."""

from datetime import date

import pytest
import pytest_asyncio
import httpx

from app.core.database import Base
from app.core.models import Briefing
from main import app
from tests.db_setup import TestSession, engine as test_engine


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """각 테스트마다 테이블 생성/삭제."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── 아카이브 ──


@pytest.mark.asyncio
async def test_archive_empty():
    """브리핑이 없을 때 아카이브 페이지가 정상 렌더링된다."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/archive")

    assert resp.status_code == 200
    assert "아직 브리핑이 없습니다" in resp.text


@pytest.mark.asyncio
async def test_archive_with_data():
    """브리핑이 있으면 목록에 표시된다."""
    # DB에 직접 데이터 삽입
    async with TestSession() as session:
        session.add(Briefing(date=date(2025, 2, 11), title="테스트 브리핑", content_html="<h2>내용</h2>"))
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/archive")

    assert resp.status_code == 200
    assert "테스트 브리핑" in resp.text


@pytest.mark.asyncio
async def test_archive_pagination_invalid_page():
    """page=0 (ge=1 위반) → 422 에러."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/archive?page=0")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_archive_detail_not_found():
    """존재하지 않는 날짜 → 404."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/archive/9999-01-01")

    assert resp.status_code == 404
