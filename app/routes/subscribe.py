"""구독 신청 API.

스프링 대응:
- EmailStr = @Email @Valid (입력 검증)
- RequestValidationError 핸들러 = @ExceptionHandler(MethodArgumentNotValidException.class)
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Subscriber

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@router.post("/subscribe")
async def subscribe(
    request: Request,
    email: EmailStr = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # 중복 체크
    existing = await db.execute(select(Subscriber).where(Subscriber.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse("landing.html", {
            "request": request,
            "message": "이미 구독 중인 이메일입니다.",
            "message_type": "warning",
        })

    subscriber = Subscriber(email=email)
    db.add(subscriber)
    await db.commit()

    return templates.TemplateResponse("landing.html", {
        "request": request,
        "message": "구독 신청이 완료되었습니다! 내일 아침 첫 브리핑을 보내드릴게요.",
        "message_type": "success",
    })
