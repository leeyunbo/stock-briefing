"""Stock Briefing - AI 주식 아침 브리핑 서비스."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.logging_config import setup_logging
from app.database import init_db
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
