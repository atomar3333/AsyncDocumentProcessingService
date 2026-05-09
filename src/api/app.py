from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.db.session import engine
from src.logging import setup_logging
from src.models.job import Base
from src.api.routes import jobs, health, metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = structlog.get_logger()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("db_tables_created")

    yield

    await engine.dispose()


app = FastAPI(
    title="Async Document Processing Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs.router, tags=["jobs"])
app.include_router(health.router, tags=["health"])
app.include_router(metrics.router, tags=["metrics"])
