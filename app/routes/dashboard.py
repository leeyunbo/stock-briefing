"""메인 대시보드 — 파이프라인 실행 캘린더 + 트렌드 키워드 맵."""

from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import Briefing, BriefingType, SeoTopic

router = APIRouter()
templates = Jinja2Templates(directory="templates")

KST = timezone(timedelta(hours=9))

# 파이프라인 표시명
_PIPELINE_LABELS = {
    BriefingType.KOSPI: "한국주식",
    BriefingType.NASDAQ: "나스닥",
    BriefingType.NEWS_DIVE: "뉴스",
    BriefingType.ISSUE_DIVE: "이슈",
    BriefingType.REAL_ESTATE: "부동산",
    BriefingType.STOCK_DEEP_DIVE: "종목",
    BriefingType.PORTFOLIO: "포트폴리오",
    BriefingType.SEO_CONTENT: "SEO",
}

_PIPELINE_ORDER = list(_PIPELINE_LABELS.keys())


def _level(total: int) -> int:
    if total == 0:
        return 0
    if total <= 2:
        return 1
    if total <= 5:
        return 2
    if total <= 8:
        return 3
    return 4


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    """메인 대시보드."""
    now_kst = datetime.now(KST)
    today = now_kst.date()

    # ── 1. 파이프라인 실행 캘린더 (최근 8주 = 56일) ──
    num_days = 56
    start_date = today - timedelta(days=num_days - 1)

    rows = await db.execute(
        select(
            Briefing.date,
            Briefing.briefing_type,
            func.count().label("cnt"),
        )
        .where(Briefing.date >= start_date)
        .group_by(Briefing.date, Briefing.briefing_type)
    )
    cal_data: dict[tuple, int] = {}
    for row in rows.all():
        cal_data[(row.date, row.briefing_type)] = row.cnt

    # 날짜별 데이터 딕셔너리 (date string key)
    all_days: list[dict] = []
    for i in range(num_days):
        d = start_date + timedelta(days=i)
        total = 0
        pipelines = {}
        for ptype in _PIPELINE_ORDER:
            cnt = cal_data.get((d, ptype), 0)
            pipelines[ptype] = cnt
            total += cnt
        all_days.append({
            "date_str": d.isoformat(),
            "display": f"{d.month}/{d.day}",
            "weekday": d.weekday(),
            "is_today": d == today,
            "total": total,
            "level": _level(total),
            "pipelines": pipelines,
        })

    # 주 단위 컬럼 (월요일 시작)
    weeks: list[list[dict | None]] = []
    current_week: list[dict | None] = [None] * 7
    for day in all_days:
        wd = day["weekday"]  # 0=Monday
        current_week[wd] = day
        if wd == 6:  # Sunday = end of week
            weeks.append(current_week)
            current_week = [None] * 7
    if any(d is not None for d in current_week):
        weeks.append(current_week)

    # ── 2. 트렌드 키워드 (source='trend') ──
    trend_rows = await db.execute(
        select(
            SeoTopic.keyword,
            SeoTopic.pattern_type,
            SeoTopic.priority,
            SeoTopic.status,
        )
        .where(SeoTopic.source == "trend")
        .order_by(SeoTopic.id.desc())
        .limit(200)
    )
    trend_keywords = []
    for row in trend_rows.all():
        trend_keywords.append({
            "keyword": row.keyword,
            "pattern": row.pattern_type,
            "priority": row.priority,
            "status": row.status,
        })

    # 패턴별 카운트
    status_counts = {"pending": 0, "published": 0, "skipped": 0}
    for tk in trend_keywords:
        s = tk["status"]
        if s in status_counts:
            status_counts[s] += 1

    # ── 3. 토픽 큐 현황 ──
    queue_rows = await db.execute(
        select(
            SeoTopic.source,
            SeoTopic.status,
            func.count().label("cnt"),
        )
        .group_by(SeoTopic.source, SeoTopic.status)
    )
    queue_stats: dict[str, dict[str, int]] = {}
    for row in queue_rows.all():
        src = row.source or "unknown"
        if src not in queue_stats:
            queue_stats[src] = {}
        queue_stats[src][row.status] = row.cnt

    # ── 4. 오늘 발행 건수 ──
    today_count_row = await db.execute(
        select(func.count()).where(Briefing.date == today)
    )
    today_count = today_count_row.scalar() or 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "today": today,
        "weeks": weeks,
        "all_days": all_days,
        "pipeline_labels": _PIPELINE_LABELS,
        "pipeline_order": _PIPELINE_ORDER,
        "trend_keywords": trend_keywords,
        "status_counts": status_counts,
        "queue_stats": queue_stats,
        "today_count": today_count,
    })
