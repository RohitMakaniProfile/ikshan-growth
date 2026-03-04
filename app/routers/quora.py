from fastapi import APIRouter
from app.services.quora_monitor import run_quora_monitor

router = APIRouter()


@router.post("/scan")
async def trigger_scan():
    """Manually trigger Quora scan — returns count of opportunities found."""
    found = run_quora_monitor()
    return {"status": "done", "opportunities_found": found}
