"""테스트 공유 Fixture.

conftest.py에 정의한 fixture는 같은 디렉토리의 모든 테스트에서 사용할 수 있다.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_db
from app.models import Subscriber, Briefing


# ── 테스트용 인메모리 DB ──

TEST_DB_URL = "sqlite+aiosqlite://"  # 인메모리 SQLite

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    """각 테스트마다 깨끗한 DB를 제공한다."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def anyio_backend():
    return "asyncio"
