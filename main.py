"""Stock Briefing - AI 주식 아침 브리핑 서비스."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.logging_config import setup_logging, correlation_id
from app.core.database import init_db
from app.routes.subscribe import router as subscribe_router
from app.routes.archive import router as archive_router
from app.scheduler import start_scheduler

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(title="Stock Briefing", lifespan=lifespan)

app.include_router(subscribe_router)
app.include_router(archive_router)

_templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """요청마다 고유한 correlation ID를 부여한다."""
    token = correlation_id.set(uuid.uuid4().hex[:8])
    try:
        response = await call_next(request)
        return response
    finally:
        correlation_id.reset(token)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 실패 시 사용자 친화적 메시지를 반환한다."""
    return _templates.TemplateResponse("landing.html", {
        "request": request,
        "message": "올바른 이메일 주소를 입력해주세요.",
        "message_type": "warning",
    }, status_code=422)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
