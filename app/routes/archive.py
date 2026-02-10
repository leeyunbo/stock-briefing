"""브리핑 아카이브 페이지."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Briefing

router = APIRouter(prefix="/archive")
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def archive_list(request: Request, q: str = "", db: AsyncSession = Depends(get_db)):
    query = select(Briefing).order_by(Briefing.date.desc())
    if q:
        query = query.where(Briefing.content_html.contains(q) | Briefing.title.contains(q))

    result = await db.execute(query)
    briefings = result.scalars().all()

    return templates.TemplateResponse("archive.html", {
        "request": request,
        "briefings": briefings,
        "search_query": q,
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
