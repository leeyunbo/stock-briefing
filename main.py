"""Stock Briefing - AI 주식 아침 브리핑 서비스."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from app.core.logging_config import setup_logging, correlation_id
from app.core.database import init_db
from app.core.http import close_http_client
from app.routes.archive import router as archive_router
from app.routes.traces import router as traces_router
from app.routes.pipelines import router as pipelines_router
from app.scheduler import start_scheduler

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown()
    await close_http_client()


app = FastAPI(title="Stock Briefing", lifespan=lifespan)

app.include_router(archive_router)
app.include_router(traces_router)
app.include_router(pipelines_router)

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
    """Pydantic 검증 실패 시 JSON 에러를 반환한다."""
    return HTMLResponse(
        content='{"error": "잘못된 요청입니다."}',
        status_code=422,
        media_type="application/json",
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
