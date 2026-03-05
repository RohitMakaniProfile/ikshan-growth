from fastapi import APIRouter

router = APIRouter()


@router.post("/scan")
async def scan_linkedin():
    """Manually trigger LinkedIn monitor scan."""
    from app.services.linkedin_monitor import run_linkedin_monitor
    alerts = run_linkedin_monitor()
    return {"status": "done", "alerts_sent": alerts}
