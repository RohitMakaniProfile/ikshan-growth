"""
IKSHAN GROWTH — FastAPI App
Blog writer + future: LinkedIn, Reddit, Quora automation
Port: 8001
"""

from contextlib import asynccontextmanager
import logging

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.routers import blog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.blog_writer import run_keyword_hunt, run_write_and_publish

    # Every Monday 9am IST — keyword hunt
    scheduler.add_job(
        run_keyword_hunt,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Asia/Kolkata"),
        id="keyword_hunt",
        replace_existing=True,
    )
    # Every day 10am IST — write + publish
    scheduler.add_job(
        run_write_and_publish,
        CronTrigger(hour=10, minute=0, timezone="Asia/Kolkata"),
        id="daily_publish",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("🚀 ikshan-growth started | Blog scheduler active (Mon 9am keywords, daily 10am post)")
    yield
    scheduler.shutdown()
    logger.info("🛑 ikshan-growth shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Ikshan Growth API",
        version="1.0.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ────────────────────────────────────────────────
    app.include_router(blog.router, prefix="/blog", tags=["Blog"])

    # Future routers — just add here when ready:
    # app.include_router(linkedin.router, prefix="/linkedin", tags=["LinkedIn"])
    # app.include_router(reddit.router,   prefix="/reddit",   tags=["Reddit"])
    # app.include_router(quora.router,    prefix="/quora",    tags=["Quora"])

    @app.get("/health")
    async def health():
        jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
        return {"status": "healthy", "scheduled_jobs": jobs}

    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
