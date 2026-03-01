"""테스트 공유 Fixture."""

import pytest
import pytest_asyncio

from app.core.database import Base, get_db
from main import app
from tests.db_setup import TestSession, engine


async def override_get_db():
    """테스트용 DB 세션을 주입한다."""
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


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
