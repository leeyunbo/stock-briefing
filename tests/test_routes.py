"""라우트 테스트."""

import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_db
from app.models import Subscriber, Briefing
from main import app

# ── 테스트용 DB 설정 ──

TEST_DB_URL = "sqlite+aiosqlite://"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    """테스트용 DB 세션을 주입한다."""
    async with TestSession() as session:
        yield session


# 의존성 교체: 실제 DB 대신 인메모리 DB 사용
app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """각 테스트마다 테이블 생성/삭제."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── 랜딩 페이지 ──


@pytest.mark.asyncio
async def test_landing_page():
    """GET / → 200 OK + HTML 반환."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ── 구독 API ──


@pytest.mark.asyncio
async def test_subscribe_valid_email():
    """유효한 이메일로 구독 시 성공 메시지."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/subscribe", data={"email": "test@example.com"})

    assert resp.status_code == 200
    assert "구독 신청이 완료되었습니다" in resp.text


@pytest.mark.asyncio
async def test_subscribe_invalid_email():
    """잘못된 이메일 형식 → 422 + 경고 메시지."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/subscribe", data={"email": "not-an-email"})

    assert resp.status_code == 422
    assert "올바른 이메일" in resp.text


@pytest.mark.asyncio
async def test_subscribe_duplicate_email():
    """중복 이메일 구독 시 경고 메시지."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 첫 번째 구독
        await client.post("/subscribe", data={"email": "dup@example.com"})
        # 두 번째 구독 (중복)
        resp = await client.post("/subscribe", data={"email": "dup@example.com"})

    assert resp.status_code == 200
    assert "이미 구독 중" in resp.text


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
        session.add(Briefing(date="2025-02-11", title="테스트 브리핑", content_html="<h2>내용</h2>"))
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
