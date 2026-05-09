import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy import select, update

from src.config import settings
from src.db.session import engine, async_session
from src.logging import setup_logging
from src.models.job import Base, Job, AuditTrail
from src.models.enums import JobStatus, AnalysisType
from src.agent.fetcher import fetch_document
from src.agent.analyzer import call_llm, validate_result

POLL_INTERVAL = 2  # seconds
STALE_TIMEOUT_MINUTES = 5
NON_TERMINAL = [JobStatus.fetching.value, JobStatus.processing.value, JobStatus.validating.value]

log = structlog.get_logger()


async def transition(session, job, to_status, reason=None):
    """Move job to a new status and log it in audit trail."""
    from_status = job.status
    job.status = to_status.value
    job.updated_at = datetime.now(timezone.utc)
    if to_status in (JobStatus.completed, JobStatus.failed):
        job.completed_at = datetime.now(timezone.utc)

    audit = AuditTrail(
        job_id=job.id,
        from_state=from_status,
        to_state=to_status.value,
        reason=reason or f"Transition {from_status} -> {to_status.value}",
    )
    session.add(audit)
    await session.commit()
    log.info("job_transition", job_id=job.id, from_state=from_status, to_state=to_status.value)


async def recover_stale_jobs():
    """On startup, reset any jobs stuck in non-terminal states back to pending."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_TIMEOUT_MINUTES)
    async with async_session() as session:
        result = await session.execute(
            select(Job).where(
                Job.status.in_(NON_TERMINAL),
                Job.updated_at < cutoff,
            )
        )
        stale_jobs = result.scalars().all()
        for job in stale_jobs:
            old_status = job.status
            job.status = JobStatus.pending.value
            job.updated_at = datetime.now(timezone.utc)
            audit = AuditTrail(
                job_id=job.id,
                from_state=old_status,
                to_state=JobStatus.pending.value,
                reason=f"Recovered stale job (was {old_status} for >{STALE_TIMEOUT_MINUTES}min)",
            )
            session.add(audit)
        await session.commit()
        if stale_jobs:
            log.warning("recovered_stale_jobs", count=len(stale_jobs))


async def claim_job():
    """Atomically claim one pending job by transitioning it to fetching."""
    async with async_session() as session:
        result = await session.execute(
            select(Job)
            .where(Job.status == JobStatus.pending.value)
            .order_by(Job.created_at.asc())
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if not job:
            return None

        await transition(session, job, JobStatus.fetching, "Worker claimed job")
        return job.id


async def process_job(job_id):
    """Process a single job through the state machine. Stub for now — agent goes here."""
    correlation_id = str(uuid.uuid4())
    log_ctx = log.bind(job_id=job_id, correlation_id=correlation_id)

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            log_ctx.error("job_not_found")
            return

        try:
            # FETCHING -> PROCESSING
            doc = await fetch_document(job.document_url)
            await transition(session, job, JobStatus.processing,
                             f"Document fetched ({doc.media_type}, {doc.page_count} pages)")

            # PROCESSING -> VALIDATING
            analysis_type = AnalysisType(job.analysis_type)
            result, usage = await call_llm(doc, analysis_type, job.token_budget)
            await transition(session, job, JobStatus.validating, "Analysis complete")

            # VALIDATING -> COMPLETED
            validated = validate_result(result, analysis_type, settings.min_confidence_threshold)
            job.result = validated
            job.token_usage = usage
            await transition(session, job, JobStatus.completed, "Validation passed")

            log_ctx.info("job_completed", tokens_used=usage.get("total_tokens", 0))

        except Exception as e:
            job.error = {"type": type(e).__name__, "detail": str(e)}
            await transition(session, job, JobStatus.failed, f"Error: {e}")
            log_ctx.error("job_failed", error=str(e))


async def poll_loop():
    """Main worker loop: poll DB for pending jobs."""
    log.info("worker_polling", interval=POLL_INTERVAL)
    while True:
        try:
            job_id = await claim_job()
            if job_id:
                await process_job(job_id)
            else:
                await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error("poll_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)


async def main():
    setup_logging()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("worker_started", concurrency=settings.worker_concurrency)

    await recover_stale_jobs()
    await poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
