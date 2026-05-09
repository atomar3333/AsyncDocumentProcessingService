import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobResponse,
    JobListResponse,
)
from src.db.session import get_session
from src.models.enums import JobStatus
from src.models.job import Job, AuditTrail

router = APIRouter()
log = structlog.get_logger()


@router.post("/jobs", response_model=JobCreateResponse, status_code=202)
async def create_job(req: JobCreateRequest, session: AsyncSession = Depends(get_session)):
    correlation_id = str(uuid.uuid4())
    idem_key = req.idempotency_key()

    # Idempotency: return existing job if same URL + type
    existing = await session.execute(
        select(Job).where(Job.idempotency_key == idem_key)
    )
    existing_job = existing.scalar_one_or_none()
    if existing_job:
        log.info("idempotent_hit", job_id=existing_job.id, correlation_id=correlation_id)
        return JobCreateResponse(id=existing_job.id, status=existing_job.status, message="Job already exists")

    # Create job
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        idempotency_key=idem_key,
        document_url=str(req.document_url),
        analysis_type=req.analysis_type.value,
        status=JobStatus.pending.value,
        token_budget=req.token_budget,
        metadata_=req.metadata or {},
    )
    session.add(job)

    # Initial audit trail entry
    audit = AuditTrail(
        job_id=job_id,
        from_state=None,
        to_state=JobStatus.pending.value,
        reason="Job created via API",
    )
    session.add(audit)
    await session.commit()

    log.info("job_created", job_id=job_id, correlation_id=correlation_id)
    return JobCreateResponse(id=job_id, status=JobStatus.pending.value)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        idempotency_key=job.idempotency_key,
        document_url=job.document_url,
        analysis_type=job.analysis_type,
        status=job.status,
        result=job.result,
        error=job.error,
        token_usage=job.token_usage,
        token_budget=job.token_budget,
        metadata=job.metadata_,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(None),
    analysis_type: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    query = select(Job)
    count_query = select(func.count()).select_from(Job)

    if status:
        query = query.where(Job.status == status)
        count_query = count_query.where(Job.status == status)
    if analysis_type:
        query = query.where(Job.analysis_type == analysis_type)
        count_query = count_query.where(Job.analysis_type == analysis_type)
    if created_after:
        query = query.where(Job.created_at >= created_after)
        count_query = count_query.where(Job.created_at >= created_after)
    if created_before:
        query = query.where(Job.created_at <= created_before)
        count_query = count_query.where(Job.created_at <= created_before)

    query = query.order_by(Job.created_at.desc()).limit(limit).offset(offset)

    result = await session.execute(query)
    jobs = result.scalars().all()

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    return JobListResponse(
        jobs=[
            JobResponse(
                id=j.id,
                idempotency_key=j.idempotency_key,
                document_url=j.document_url,
                analysis_type=j.analysis_type,
                status=j.status,
                result=j.result,
                error=j.error,
                token_usage=j.token_usage,
                token_budget=j.token_budget,
                metadata=j.metadata_,
                created_at=j.created_at,
                updated_at=j.updated_at,
                completed_at=j.completed_at,
            )
            for j in jobs
        ],
        total=total,
    )
