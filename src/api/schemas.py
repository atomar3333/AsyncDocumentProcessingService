import hashlib
from datetime import datetime
from typing import Optional, Dict, List

from pydantic import BaseModel, Field, HttpUrl

from src.models.enums import AnalysisType, JobStatus


# ── Request schemas ──

class JobCreateRequest(BaseModel):
    document_url: HttpUrl
    analysis_type: AnalysisType
    token_budget: int = Field(default=4096, ge=100, le=32000)
    metadata: Optional[dict] = None

    def idempotency_key(self) -> str:
        raw = f"{self.document_url}:{self.analysis_type.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ── Response schemas ──

class JobResponse(BaseModel):
    id: str
    idempotency_key: str
    document_url: str
    analysis_type: str
    status: str
    result: Optional[dict] = None
    error: Optional[dict] = None
    token_usage: Optional[dict] = None
    token_budget: int
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobCreateResponse(BaseModel):
    id: str
    status: str
    message: str = "Job accepted"


class JobListResponse(BaseModel):
    jobs: List[JobResponse]
    total: int


class HealthResponse(BaseModel):
    status: str
    checks: dict


class MetricsResponse(BaseModel):
    total_jobs: int
    jobs_by_status: Dict[str, int]
    error_rate: float
    avg_latency_seconds: Optional[float]
    total_token_spend: int
