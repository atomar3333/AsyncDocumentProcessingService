from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/docprocessor.db"
    redis_url: str = "redis://redis:6379/0"
    gemini_api_key: str = ""
    log_level: str = "info"
    token_budget_default: int = 4096
    max_document_size_mb: int = 10
    worker_concurrency: int = 5
    min_confidence_threshold: float = 0.5

    class Config:
        env_file = ".env"


settings = Settings()
