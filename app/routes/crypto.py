"""코인 자동매매 대시보드."""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.trading.models import CryptoPosition, CryptoSnapshot, CryptoTrade, StrategyState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crypto")
templates = Jinja2Templates(directory="templates")

KST = timezone(timedelta(hours=9))


@router.get("", response_class=HTMLResponse)
async def crypto_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """코인 자동매매 대시보드."""
    s = get_settings()

    # 1. 현재 포지션
    result = await db.execute(
        select(CryptoPosition).where(CryptoPosition.is_active.is_(True))
    )
    positions = list(result.scalars().all())

    # 2. 최근 거래 (50건)
    result = await db.execute(
        select(CryptoTrade)
        .order_by(CryptoTrade.trade_date.desc())
        .limit(50)
    )
    trades = list(result.scalars().all())

    # 3. 최근 스냅샷 (30일)
    result = await db.execute(
        select(CryptoSnapshot)
        .order_by(CryptoSnapshot.snapshot_date.desc())
        .limit(30)
    )
    snapshots = list(result.scalars().all())
    snapshots.reverse()  # 날짜순

    # 4. 현재 전략 상태
    result = await db.execute(
        select(StrategyState).order_by(StrategyState.id.desc()).limit(1)
    )
    strategy = result.scalar_one_or_none()

    # 5. 오늘 거래 통계
    today_start = datetime.combine(datetime.now(KST).date(), datetime.min.time())
    result = await db.execute(
        select(
            func.count(CryptoTrade.id).label("count"),
            func.sum(CryptoTrade.fee).label("total_fee"),
        ).where(CryptoTrade.trade_date >= today_start)
    )
    today_stats = result.one()

    # 6. 스냅샷 차트 데이터
    chart_dates = [s.snapshot_date.strftime("%m/%d") for s in snapshots]
    chart_values = [s.total_krw for s in snapshots]
    chart_returns = [s.return_pct for s in snapshots]

    # 7. 포지션별 현재가 (최신 스냅샷에서)
    latest_positions_json = {}
    if snapshots:
        try:
            latest_positions_json = json.loads(snapshots[-1].positions_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return templates.TemplateResponse("crypto_trading.html", {
        "request": request,
        "positions": positions,
        "trades": trades,
        "snapshots": snapshots,
        "strategy": strategy,
        "today_trade_count": today_stats.count or 0,
        "today_total_fee": today_stats.total_fee or 0,
        "chart_dates": json.dumps(chart_dates),
        "chart_values": json.dumps(chart_values),
        "chart_returns": json.dumps(chart_returns),
        "latest_positions": latest_positions_json,
        "initial_capital": s.upbit_initial_capital,
        "trading_enabled": s.upbit_trading_enabled,
        "kst": KST,
    })
