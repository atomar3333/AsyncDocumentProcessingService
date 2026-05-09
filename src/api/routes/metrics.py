from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import MetricsResponse
from src.db.session import get_session
from src.models.job import Job
from src.models.enums import JobStatus

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(session: AsyncSession = Depends(get_session)):
    # Total jobs
    total = (await session.execute(select(func.count()).select_from(Job))).scalar() or 0

    # Jobs by status
    status_rows = await session.execute(
        select(Job.status, func.count()).group_by(Job.status)
    )
    jobs_by_status = {row[0]: row[1] for row in status_rows}

    # Error rate
    failed = jobs_by_status.get(JobStatus.failed.value, 0)
    error_rate = (failed / total) if total > 0 else 0.0

    # Average latency (pending -> completed)
    latency_result = await session.execute(
        select(
            func.avg(
                func.julianday(Job.completed_at) - func.julianday(Job.created_at)
            )
        ).where(Job.completed_at.isnot(None))
    )
    avg_julian_days = latency_result.scalar()
    avg_latency_seconds = round(avg_julian_days * 86400, 2) if avg_julian_days else None

    # Total token spend
    # token_usage is JSON like {"input_tokens": X, "output_tokens": Y, "total_tokens": Z}
    # SQLite JSON extraction
    all_jobs = await session.execute(
        select(Job.token_usage).where(Job.token_usage.isnot(None))
    )
    total_tokens = 0
    for (usage,) in all_jobs:
        if isinstance(usage, dict):
            total_tokens += usage.get("total_tokens", 0)

    return MetricsResponse(
        total_jobs=total,
        jobs_by_status=jobs_by_status,
        error_rate=round(error_rate, 4),
        avg_latency_seconds=avg_latency_seconds,
        total_token_spend=total_tokens,
    )
