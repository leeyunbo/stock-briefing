"""지수 스냅샷 저장/조회 테스트."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.collector.market import MarketSummary, IndexData
from app.collector.nasdaq import NasdaqSummary, USIndexData
from app.core.database import Base
from app.core.models import IndexSnapshot
from tests.db_setup import TestSession, engine as test_engine


@pytest_asyncio.fixture
async def snapshot_db():
    """스냅샷 테스트용 DB를 생성/정리한다."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── save_kospi_snapshot 테스트 ──


@pytest.mark.asyncio
async def test_save_kospi_snapshot(snapshot_db):
    """KOSPI/KOSDAQ 스냅샷이 DB에 저장된다."""
    from app.collector.snapshot import save_kospi_snapshot

    market = MarketSummary(
        date="2026-02-27",
        kospi=IndexData(name="코스피", close="2,600", change="30", change_pct="1.20", direction="상승"),
        kosdaq=IndexData(name="코스닥", close="800", change="-5", change_pct="-0.63", direction="하락"),
    )

    with patch("app.collector.snapshot.async_session", TestSession):
        await save_kospi_snapshot(market)

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(IndexSnapshot))
        rows = list(result.scalars().all())

    assert len(rows) == 2
    kospi = next(r for r in rows if r.market == "kospi")
    assert kospi.index_name == "코스피"
    assert kospi.close == "2,600"
    assert kospi.change_pct == "1.20"
    kosdaq = next(r for r in rows if r.market == "kosdaq")
    assert kosdaq.index_name == "코스닥"


@pytest.mark.asyncio
async def test_save_kospi_snapshot_duplicate_skip(snapshot_db):
    """중복 저장 시 에러 없이 무시된다."""
    from app.collector.snapshot import save_kospi_snapshot

    market = MarketSummary(
        date="2026-02-27",
        kospi=IndexData(name="코스피", close="2,600", change="30", change_pct="1.20", direction="상승"),
    )

    with patch("app.collector.snapshot.async_session", TestSession):
        await save_kospi_snapshot(market)
        await save_kospi_snapshot(market)  # 중복 — skip

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(IndexSnapshot))
        rows = list(result.scalars().all())

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_save_kospi_snapshot_no_date(snapshot_db):
    """date가 비어있으면 저장하지 않는다."""
    from app.collector.snapshot import save_kospi_snapshot

    market = MarketSummary(date="")

    with patch("app.collector.snapshot.async_session", TestSession):
        await save_kospi_snapshot(market)

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(IndexSnapshot))
        rows = list(result.scalars().all())

    assert len(rows) == 0


# ── save_nasdaq_snapshot 테스트 ──


@pytest.mark.asyncio
async def test_save_nasdaq_snapshot(snapshot_db):
    """NASDAQ 3대 지수 스냅샷이 DB에 저장된다."""
    from app.collector.snapshot import save_nasdaq_snapshot

    summary = NasdaqSummary(
        date="2026-02-27",
        indices=[
            USIndexData(name="나스닥 100", close="520.32", change="+2.10", change_pct="+0.40", direction="상승"),
            USIndexData(name="S&P 500", close="580.11", change="-1.05", change_pct="-0.18", direction="하락"),
            USIndexData(name="다우존스", close="430.55", change="+0.50", change_pct="+0.12", direction="상승"),
        ],
    )

    with patch("app.collector.snapshot.async_session", TestSession):
        await save_nasdaq_snapshot(summary)

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(IndexSnapshot))
        rows = list(result.scalars().all())

    assert len(rows) == 3
    markets = {r.market for r in rows}
    assert markets == {"nasdaq", "sp500", "dow"}


# ── fetch_index_history 테스트 ──


@pytest.mark.asyncio
async def test_fetch_index_history(snapshot_db):
    """과거 N일 스냅샷을 조회한다."""
    from app.collector.snapshot import fetch_index_history

    # 데이터 직접 삽입
    async with TestSession() as session:
        for i in range(5):
            d = date.today() - timedelta(days=i + 1)
            session.add(IndexSnapshot(
                date=d, market="kospi", index_name="코스피",
                close=f"{2600 + i}", change_pct=f"{0.5 + i * 0.1:.1f}", direction="상승",
            ))
        await session.commit()

    with patch("app.collector.snapshot.async_session", TestSession):
        history = await fetch_index_history(["kospi"])

    assert len(history) == 5
    # 최신순 정렬
    assert history[0].date > history[-1].date


# ── fetch_latest_nasdaq 테스트 ──


@pytest.mark.asyncio
async def test_fetch_latest_nasdaq(snapshot_db):
    """가장 최근 나스닥 스냅샷을 조회한다."""
    from app.collector.snapshot import fetch_latest_nasdaq

    # 2일치 데이터 삽입
    async with TestSession() as session:
        for i, d in enumerate([date.today() - timedelta(days=2), date.today() - timedelta(days=1)]):
            session.add(IndexSnapshot(
                date=d, market="nasdaq", index_name="나스닥 100",
                close=f"{520 + i}", change_pct=f"+0.{i}0", direction="상승",
            ))
            session.add(IndexSnapshot(
                date=d, market="sp500", index_name="S&P 500",
                close=f"{580 + i}", change_pct=f"-0.{i}0", direction="하락",
            ))
        await session.commit()

    with patch("app.collector.snapshot.async_session", TestSession):
        latest = await fetch_latest_nasdaq()

    assert len(latest) == 2
    # 가장 최근 날짜만
    dates = {s.date for s in latest}
    assert len(dates) == 1
    assert dates.pop() == date.today() - timedelta(days=1)


@pytest.mark.asyncio
async def test_fetch_latest_nasdaq_empty(snapshot_db):
    """데이터가 없으면 빈 리스트를 반환한다."""
    from app.collector.snapshot import fetch_latest_nasdaq

    with patch("app.collector.snapshot.async_session", TestSession):
        latest = await fetch_latest_nasdaq()

    assert latest == []
