from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/evalhub"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 1440
    fernet_key: str = ""
    s3_endpoint_url: str | None = None
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket: str = "evalhub-datasets"
    max_upload_bytes: int = 50 * 1024 * 1024
    max_dataset_rows: int = 5000
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    eval_batch_size: int = 8
    evaluation_lease_seconds: int = 900
    allow_private_endpoints: bool = False
    endpoint_timeout_seconds: float = 60
    endpoint_retries: int = 2
    max_document_bytes: int = 20 * 1024 * 1024
    max_document_expanded_bytes: int = 100 * 1024 * 1024
    max_document_pages: int = 2000
    max_document_chars: int = 20_000_000
    document_parse_timeout_seconds: float = 30
    document_parse_memory_bytes: int = 512 * 1024 * 1024
    max_documents_per_job: int = 10
    generation_chunk_chars: int = 2000
    generation_context_chars: int = 300_000
    generation_lease_seconds: int = 900
    provider_discovery_timeout_seconds: float = 10
    provider_discovery_max_bytes: int = 2 * 1024 * 1024
    max_custom_connections: int = 20
    judge_max_tokens: int = 8192
    generation_max_tokens: int = 8192


settings = Settings()
