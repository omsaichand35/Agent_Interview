"""Integration tests for D6: Production Configuration.

Verifies:
- Development configuration loads with sensible defaults.
- Production configuration loads and validates readiness.
- Missing or weak secrets in production fail fast.
- SQLite or missing database URL in production fails clearly.
- ML model path validation detects valid/missing weights.
- CORS cannot be wildcard in production.
- Feature flags toggle features without code changes.
- Environment variables cleanly override defaults.
"""
import pytest
from app.config import ConfigurationError, Settings


def test_development_configuration_loads():
    """Development configuration loads with local SQLite and debug mode."""
    dev_settings = Settings(
        environment="development",
        debug=True,
        database_url="sqlite:///./data/dev.db",
        cors_origins="http://localhost:3000,http://127.0.0.1:3000",
    )
    assert dev_settings.environment == "development"
    assert dev_settings.debug is True
    assert dev_settings.database_url.startswith("sqlite")
    assert "http://localhost:3000" in dev_settings.get_cors_origins()
    assert dev_settings.enable_voice is True
    assert dev_settings.enable_tts is True
    assert dev_settings.enable_identity is True
    assert dev_settings.enable_background_jobs is True


def test_production_configuration_loads():
    """Production configuration passes validation when strong secrets and PostgreSQL are configured."""
    prod_settings = Settings(
        environment="production",
        debug=False,
        database_url="postgresql://prod_user:SuperSecretPassword123@db.prod.internal:5432/hiring_db",
        jwt_secret_key="production_cryptographic_secret_key_minimum_32_bytes_long",
        cors_origins="https://recruiter.company.com,https://interview.company.com",
    )
    assert prod_settings.environment == "production"
    assert prod_settings.debug is False
    assert prod_settings.jwt_secret == "production_cryptographic_secret_key_minimum_32_bytes_long"
    assert "https://recruiter.company.com" in prod_settings.get_cors_origins()
    assert "*" not in prod_settings.get_cors_origins()

    # Must validate readiness without error
    prod_settings.validate_production_readiness()


def test_missing_production_secret_fails():
    """Production startup fails if JWT secret is missing or insecure default."""
    insecure_keys = [
        "",
        "secret123",
        "secret",
        "ai_hiring_platform_super_secret_key_change_in_production",
    ]

    for bad_key in insecure_keys:
        bad_settings = Settings(
            environment="production",
            database_url="postgresql://user:pass@host:5432/db",
            jwt_secret_key=bad_key,
            cors_origins="https://app.company.com",
        )
        with pytest.raises((RuntimeError, ValueError)) as exc_info:
            bad_settings.validate_production_readiness()
        assert "JWT_SECRET_KEY" in str(exc_info.value) or "secret" in str(exc_info.value).lower()


def test_invalid_database_url_fails_clearly():
    """Production startup fails clearly if SQLite or empty database URL is used."""
    sqlite_prod = Settings(
        environment="production",
        database_url="sqlite:///./data/prod.db",
        jwt_secret_key="production_cryptographic_secret_key_minimum_32_bytes_long",
        cors_origins="https://app.company.com",
    )
    with pytest.raises((RuntimeError, ValueError)) as exc_info:
        sqlite_prod.validate_production_readiness()
    assert "DATABASE_URL" in str(exc_info.value) or "PostgreSQL" in str(exc_info.value)

    empty_db_prod = Settings(
        environment="production",
        database_url="",
        jwt_secret_key="production_cryptographic_secret_key_minimum_32_bytes_long",
        cors_origins="https://app.company.com",
    )
    with pytest.raises((RuntimeError, ValueError)):
        empty_db_prod.validate_production_readiness()


def test_model_path_validation_works():
    """Model path validation verifies existing model files and flags missing ones."""
    settings = Settings()
    validation = settings.validate_model_paths()

    # The actual workspace should have existing ONNX models
    assert "sface" in validation
    assert "yunet" in validation
    assert validation["sface"] is True
    assert validation["yunet"] is True

    # When paths are invalid
    missing_settings = Settings(
        sface_model_path="models/face/non_existent_sface.onnx",
        yunet_model_path="models/face/non_existent_yunet.onnx",
    )
    missing_validation = missing_settings.validate_model_paths()
    assert missing_validation["sface"] is False
    assert missing_validation["yunet"] is False

    with pytest.raises(FileNotFoundError):
        missing_settings.validate_model_paths(raise_on_missing=True)


def test_cors_isnt_wildcard_in_production():
    """CORS in production must never allow wildcard '*' and fails validation if attempted."""
    wildcard_prod = Settings(
        environment="production",
        database_url="postgresql://user:pass@host:5432/db",
        jwt_secret_key="production_cryptographic_secret_key_minimum_32_bytes_long",
        cors_origins="*",
    )

    # get_cors_origins filters out wildcard in production
    assert "*" not in wildcard_prod.get_cors_origins()

    # validate_production_readiness strictly rejects wildcard configuration
    with pytest.raises((RuntimeError, ValueError)) as exc_info:
        wildcard_prod.validate_production_readiness()
    assert "CORS" in str(exc_info.value)

    # In development, wildcard is permitted for local convenience
    dev_settings = Settings(environment="development", cors_origins="*")
    assert "*" in dev_settings.get_cors_origins()


def test_feature_flags_work():
    """Feature flags can disable subsystems independently for graceful degradation."""
    # Default is enabled
    standard_settings = Settings()
    assert standard_settings.enable_voice is True
    assert standard_settings.enable_tts is True
    assert standard_settings.enable_identity is True
    assert standard_settings.enable_background_jobs is True

    # Can selectively disable TTS when broken or voice when not supported
    degraded_settings = Settings(
        enable_tts=False,
        enable_voice=False,
        enable_identity=False,
        enable_background_jobs=False,
    )
    assert degraded_settings.enable_voice is False
    assert degraded_settings.enable_tts is False
    assert degraded_settings.enable_identity is False
    assert degraded_settings.enable_background_jobs is False


def test_environment_variables_override_defaults(monkeypatch):
    """Environment variables cleanly override default configurations."""
    monkeypatch.setenv("LLM_MODEL", "meta/llama-3.1-70b-instruct")
    monkeypatch.setenv("WHISPER_MODEL", "large-v3")
    monkeypatch.setenv("IDENTITY_MATCHER", "sface_custom")
    monkeypatch.setenv("FACE_MATCH_THRESHOLD", "0.85")
    monkeypatch.setenv("ENABLE_TTS", "false")

    custom_settings = Settings()
    assert custom_settings.llm_model == "meta/llama-3.1-70b-instruct"
    assert custom_settings.whisper_model == "large-v3"
    assert custom_settings.identity_matcher == "sface_custom"
    assert custom_settings.face_match_threshold == 0.85
    assert custom_settings.enable_tts is False
