"""구독 신청 API.

스프링 대응:
- EmailStr = @Email @Valid (입력 검증)
- RequestValidationError 핸들러 = @ExceptionHandler(MethodArgumentNotValidException.class)
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import Subscriber

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


@router.post("/subscribe")
async def subscribe(
    request: Request,
    email: EmailStr = Form(...),
    db: AsyncSession = Depends(get_db),
):
    subscriber = Subscriber(email=email)
    db.add(subscriber)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return templates.TemplateResponse("landing.html", {
            "request": request,
            "message": "이미 구독 중인 이메일입니다.",
            "message_type": "warning",
        })

    await db.commit()

    return templates.TemplateResponse("landing.html", {
        "request": request,
        "message": "구독 신청이 완료되었습니다! 내일 아침 첫 브리핑을 보내드릴게요.",
        "message_type": "success",
    })
