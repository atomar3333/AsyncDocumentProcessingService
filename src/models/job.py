import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON, TypeDecorator
from sqlalchemy.orm import declarative_base, relationship

from src.models.enums import JobStatus, AnalysisType

Base = declarative_base()


class SQLiteDateTime(TypeDecorator):
    """Handle SQLite ISO datetime strings with 'Z' suffix."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        # Handle trailing Z
        v = value.replace("Z", "+00:00")
        return datetime.fromisoformat(v)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String(64), unique=True, nullable=False, index=True)
    correlation_id = Column(String(36), nullable=True)
    document_url = Column(Text, nullable=False)
    analysis_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default=JobStatus.pending.value)
    result = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)
    token_usage = Column(JSON, nullable=True)
    token_budget = Column(Integer, nullable=False, default=4096)
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)
    created_at = Column(SQLiteDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(SQLiteDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(SQLiteDateTime, nullable=True)

    audit_trail = relationship("AuditTrail", back_populates="job", order_by="AuditTrail.timestamp")


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    from_state = Column(String(20), nullable=True)
    to_state = Column(String(20), nullable=False)
    reason = Column(Text, nullable=True)
    timestamp = Column(SQLiteDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="audit_trail")
