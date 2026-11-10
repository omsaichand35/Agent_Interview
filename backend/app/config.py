import os
from pathlib import Path
from typing import Dict, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.paths import get_project_root, resolve_path


def get_env_files() -> List[str]:
    """Discovers environment configuration files with hierarchical precedence."""
    env = os.environ.get("ENVIRONMENT", os.environ.get("APP_ENV", "development")).lower()
    root = get_project_root()
    backend_dir = Path(__file__).resolve().parent.parent

    files = [
        f".env.{env}",
        str(backend_dir / f".env.{env}"),
        str(root / f".env.{env}"),
        ".env",
        str(backend_dir / ".env"),
        str(root / ".env"),
    ]
    # Filter to existing files
    return [f for f in files if Path(f).is_file()]


class ConfigurationError(RuntimeError, ValueError):
    """Raised when application configuration fails validation."""
    pass


class Settings(BaseSettings):
    # Application & Environment
    app_name: str = "AI Hiring Pipeline"
    environment: str = "development"  # development, staging, production
    debug: bool = True
    api_prefix: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./data/interview.db"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    # Authentication & Secrets
    jwt_secret_key: str = "ai_hiring_platform_super_secret_key_change_in_production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Outbound transactional email (SMTP). Leave host empty to disable delivery.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Graduate Admissions"
    smtp_use_ssl: bool = False
    smtp_starttls: bool = True
    public_base_url: str = "http://localhost:8000"

    @property
    def jwt_secret(self) -> str:
        return self.jwt_secret_key

    # AI & LLM Configuration
    llm_provider: str = "nvidia"
    llm_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    llm_temperature: float = 0.2
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

    # Identity Verification
    identity_matcher: str = "sface"
    face_match_threshold: float = 0.70
    sface_model_path: str = "models/face/face_recognition_sface_2021dec.onnx"
    yunet_model_path: str = "models/face/face_detection_yunet_2023mar.onnx"

    # Voice (STT & TTS)
    whisper_model: str = "small"
    stt_enabled: bool = True
    tts_enabled: bool = True
    audio_upload_max_bytes: int = 50 * 1024 * 1024  # 50 MB

    # Storage Paths
    resume_upload_dir: str = "data/outputs/resumes"
    recording_upload_dir: str = "data/outputs/interviews"
    identity_logs_dir: str = "data/outputs/identity_logs"
    jobs_storage_dir: str = "data/outputs/jobs"
    vector_db_path: str = "data/processed/vector_store"

    # Infrastructure & Networking
    redis_url: str = ""
    redis_required: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000"

    # Feature Flags (D6.5)
    enable_voice: bool = True
    enable_tts: bool = True
    enable_identity: bool = True
    enable_background_jobs: bool = True

    # Scoring Weights
    resume_weight: float = 0.40
    interview_weight: float = 0.60

    # Data Retention Configuration (F1.6)
    resume_retention_days: int = 180
    audio_retention_days: int = 30
    identity_retention_days: int = 14
    transcript_retention_days: int = 90
    audit_retention_days: int = 365

    model_config = SettingsConfigDict(
        env_file=get_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    def get_cors_origins(self) -> List[str]:
        """Returns parsed CORS origins, disallowing wildcards in production."""
        raw_origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if self.environment.lower() == "production":
            return [o for o in raw_origins if o != "*"]
        return raw_origins or ["*"]

    def validate_model_paths(self, raise_on_missing: bool = False) -> Dict[str, bool]:
        """Validates existence of local ML models on disk."""
        sface = resolve_path(self.sface_model_path)
        yunet = resolve_path(self.yunet_model_path)
        status = {
            "sface": sface.exists() and sface.is_file(),
            "yunet": yunet.exists() and yunet.is_file(),
        }
        if raise_on_missing and not all(status.values()):
            missing = [k for k, v in status.items() if not v]
            raise FileNotFoundError(f"Required model files missing: {', '.join(missing)}")
        return status

    def validate_production_readiness(self) -> None:
        """Validates critical security rules for production environments."""
        if self.environment.lower() == "production":
            insecure_secrets = [
                "ai_hiring_platform_super_secret_key_change_in_production",
                "secret123",
                "secret",
                "changeme",
                "default",
                "",
            ]
            if not self.jwt_secret_key or self.jwt_secret_key.strip().lower() in insecure_secrets:
                raise ConfigurationError(
                    "Production startup rejected: JWT_SECRET_KEY must be a strong, non-default secret."
                )

            if not self.database_url or self.database_url.startswith("sqlite"):
                raise ConfigurationError(
                    "Production startup rejected: DATABASE_URL must configure a PostgreSQL cluster, not SQLite."
                )

            origins = self.get_cors_origins()
            raw_tokens = [t.strip() for t in self.cors_origins.split(",")]
            if not origins or "*" in raw_tokens:
                raise ConfigurationError(
                    "Production startup rejected: CORS_ORIGINS must specify explicit production origins (no wildcard '*')."
                )


settings = Settings()


def refresh_smtp_settings() -> None:
    """Reload SMTP values from the active environment files before mail work.

    This lets a long-lived development process pick up credentials added to
    backend/.env without retaining the empty settings it started with.
    """
    fresh = Settings(_env_file=get_env_files(), _env_file_encoding="utf-8")
    for name in (
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_from_email",
        "smtp_from_name",
        "smtp_use_ssl",
        "smtp_starttls",
    ):
        setattr(settings, name, getattr(fresh, name))

# Validate when explicitly running in production
if settings.environment.lower() == "production":
    settings.validate_production_readiness()
