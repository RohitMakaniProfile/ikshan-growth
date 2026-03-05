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
from app.routers import blog, reddit, quora, linkedin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.blog_writer import run_keyword_hunt, run_write_and_publish
    from app.services.reddit_monitor import run_reddit_monitor
    from app.services.quora_monitor import run_quora_monitor
    from app.services.linkedin_monitor import run_linkedin_monitor

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
    # Every 6 hours — Reddit monitor (find questions + draft answers)
    scheduler.add_job(
        run_reddit_monitor,
        CronTrigger(hour="0,6,12,18", minute=0, timezone="Asia/Kolkata"),
        id="reddit_monitor",
        replace_existing=True,
    )
    # Every 8 hours — Quora monitor (find questions + draft answers)
    scheduler.add_job(
        run_quora_monitor,
        CronTrigger(hour="2,10,18", minute=0, timezone="Asia/Kolkata"),
        id="quora_monitor",
        replace_existing=True,
    )
    # Every 12 hours — LinkedIn monitor (trending hashtags + post drafts)
    scheduler.add_job(
        run_linkedin_monitor,
        CronTrigger(hour="7,19", minute=0, timezone="Asia/Kolkata"),
        id="linkedin_monitor",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("ikshan-growth | Blog: 10am | Reddit: 6h | Quora: 8h | LinkedIn: 12h")
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
    app.include_router(blog.router,     prefix="/blog",     tags=["Blog"])
    app.include_router(reddit.router,   prefix="/reddit",   tags=["Reddit"])
    app.include_router(quora.router,    prefix="/quora",    tags=["Quora"])
    app.include_router(linkedin.router, prefix="/linkedin", tags=["LinkedIn"])

    @app.get("/health")
    async def health():
        jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
        return {"status": "healthy", "scheduled_jobs": jobs}

    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
