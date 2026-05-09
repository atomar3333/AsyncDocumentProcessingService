import enum


class JobStatus(str, enum.Enum):
    pending = "pending"
    fetching = "fetching"
    processing = "processing"
    validating = "validating"
    completed = "completed"
    failed = "failed"


class AnalysisType(str, enum.Enum):
    summary = "summary"
    extraction = "extraction"
    classification = "classification"
