"""브리핑 아카이브 페이지.

스프링 대응:
- Query(ge=1) = @RequestParam @Min(1) (파라미터 검증)
- offset/limit = Pageable + Page<T> (페이지네이션)
- func.count() = JPA의 countQuery (전체 건수 조회)
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Briefing

router = APIRouter(prefix="/archive")
templates = Jinja2Templates(directory="templates")

PAGE_SIZE = 10


@router.get("", response_class=HTMLResponse)
async def archive_list(
    request: Request,
    q: str = "",
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    base_query = select(Briefing)
    if q:
        base_query = base_query.where(
            Briefing.content_html.contains(q) | Briefing.title.contains(q)
        )

    # 전체 건수 조회 (페이지 계산용)
    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = count_result.scalar()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # offset/limit 페이지네이션
    offset = (page - 1) * PAGE_SIZE
    rows = await db.execute(
        base_query.order_by(Briefing.date.desc()).offset(offset).limit(PAGE_SIZE)
    )
    briefings = rows.scalars().all()

    return templates.TemplateResponse("archive.html", {
        "request": request,
        "briefings": briefings,
        "search_query": q,
        "page": page,
        "total_pages": total_pages,
    })


@router.get("/{briefing_date}", response_class=HTMLResponse)
async def archive_detail(request: Request, briefing_date: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Briefing).where(Briefing.date == briefing_date))
    briefing = result.scalar_one_or_none()

    if not briefing:
        return HTMLResponse("<h1>해당 날짜의 브리핑이 없습니다.</h1>", status_code=404)

    return templates.TemplateResponse("briefing_detail.html", {
        "request": request,
        "briefing": briefing,
    })
