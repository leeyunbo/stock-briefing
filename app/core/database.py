from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

_settings = get_settings()
engine = create_async_engine(_settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_async_url = _settings.database_url
if "+aiosqlite" in _async_url:
    _sync_url = _async_url.replace("+aiosqlite", "")
elif "+asyncpg" in _async_url:
    _sync_url = _async_url.replace("+asyncpg", "+psycopg2")
elif "+aiomysql" in _async_url:
    _sync_url = _async_url.replace("+aiomysql", "+pymysql")
else:
    _sync_url = _async_url
sync_engine = create_engine(_sync_url, echo=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session
