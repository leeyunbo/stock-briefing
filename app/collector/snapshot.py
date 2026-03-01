"""지수 스냅샷 저장/조회 — 과거 추이 + 크로스 파이프라인 참조용.

매일 파이프라인 실행 시 당일 지수를 DB에 저장하고,
프롬프트 생성 시 과거 N일 데이터를 조회한다.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from app.collector.market import MarketSummary
from app.collector.nasdaq import NasdaqSummary
from app.core.database import async_session
from app.core.models import IndexSnapshot

logger = logging.getLogger(__name__)


async def _save_snapshots(rows: list[dict], label: str) -> None:
    """스냅샷 행들을 DB에 저장한다 (중복 시 skip)."""
    if not rows:
        return
    async with async_session() as session:
        for row in rows:
            stmt = sqlite_upsert(IndexSnapshot).values(**row)
            stmt = stmt.on_conflict_do_nothing(index_elements=["date", "market", "index_name"])
            await session.execute(stmt)
        await session.commit()
    logger.info("%s 스냅샷 저장: %s (%d건)", label, rows[0]["date"], len(rows))


async def save_kospi_snapshot(market: MarketSummary) -> None:
    """KOSPI/KOSDAQ 당일 지수를 DB에 저장한다 (중복 시 skip)."""
    if not market.date:
        return
    market_date = date.fromisoformat(market.date)
    rows = [
        {"date": market_date, "market": code, "index_name": idx.name,
         "close": idx.close, "change_pct": idx.change_pct, "direction": idx.direction}
        for idx, code in [(market.kospi, "kospi"), (market.kosdaq, "kosdaq")]
        if idx
    ]
    await _save_snapshots(rows, "KOSPI/KOSDAQ")


async def save_nasdaq_snapshot(summary: NasdaqSummary) -> None:
    """NASDAQ 3대 지수를 DB에 저장한다."""
    if not summary.date:
        return
    market_date = date.fromisoformat(summary.date)
    market_map = {"나스닥 100": "nasdaq", "S&P 500": "sp500", "다우존스": "dow"}
    rows = [
        {"date": market_date, "market": market_map.get(idx.name, "us"),
         "index_name": idx.name, "close": idx.close,
         "change_pct": idx.change_pct, "direction": idx.direction}
        for idx in summary.indices
    ]
    await _save_snapshots(rows, "NASDAQ")


async def fetch_index_history(
    markets: list[str],
    days: int = 5,
) -> list[IndexSnapshot]:
    """과거 N일 지수 스냅샷을 DB에서 조회한다."""
    async with async_session() as session:
        stmt = (
            select(IndexSnapshot)
            .where(IndexSnapshot.market.in_(markets))
            .order_by(IndexSnapshot.date.desc())
            .limit(days * len(markets))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def fetch_latest_nasdaq() -> list[IndexSnapshot]:
    """DB에서 가장 최근 날짜의 나스닥 스냅샷을 조회한다."""
    nasdaq_markets = ["nasdaq", "sp500", "dow"]
    async with async_session() as session:
        # 가장 최근 날짜 조회
        latest_date_stmt = (
            select(IndexSnapshot.date)
            .where(IndexSnapshot.market.in_(nasdaq_markets))
            .order_by(IndexSnapshot.date.desc())
            .limit(1)
        )
        result = await session.execute(latest_date_stmt)
        latest_date = result.scalar_one_or_none()
        if not latest_date:
            return []

        # 해당 날짜의 모든 나스닥 스냅샷 조회
        stmt = (
            select(IndexSnapshot)
            .where(
                IndexSnapshot.market.in_(nasdaq_markets),
                IndexSnapshot.date == latest_date,
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
