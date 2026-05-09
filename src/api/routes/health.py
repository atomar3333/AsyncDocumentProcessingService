import structlog
from fastapi import APIRouter
from sqlalchemy import text

from src.api.schemas import HealthResponse
from src.db.session import engine

router = APIRouter()
log = structlog.get_logger()


@router.get("/healthz", response_model=HealthResponse)
async def healthz():
    checks = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)
        log.error("healthcheck_db_failed", error=str(e))

    healthy = all(v == "ok" for v in checks.values())
    return HealthResponse(
        status="healthy" if healthy else "degraded",
        checks=checks,
    )
