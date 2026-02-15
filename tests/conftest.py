"""테스트 공유 Fixture — 스프링의 @TestConfiguration + @MockBean 역할.

conftest.py는 pytest가 자동으로 인식하는 파일로,
여기에 정의한 fixture는 같은 디렉토리의 모든 테스트에서 사용할 수 있다.
스프링의 @TestConfiguration 빈들이 모든 @SpringBootTest에서 공유되는 것과 같다.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_db
from app.models import Subscriber, Briefing


# ── 테스트용 인메모리 DB ──
# 스프링의 @DataJpaTest가 H2 인메모리 DB를 쓰는 것과 동일

TEST_DB_URL = "sqlite+aiosqlite://"  # 인메모리 SQLite

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    """각 테스트마다 깨끗한 DB를 제공한다.

    스프링의 @Transactional 테스트처럼
    테스트 시작 시 테이블 생성 → 테스트 끝나면 테이블 삭제.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def anyio_backend():
    return "asyncio"
