from fastapi import APIRouter
from app.services.reddit_monitor import run_reddit_monitor

router = APIRouter()


@router.post("/scan")
async def trigger_scan():
    """Manually trigger Reddit scan — returns count of opportunities found."""
    found = run_reddit_monitor()
    return {"status": "done", "opportunities_found": found}
