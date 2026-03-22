"""Unit tests for config module."""

import pytest
from pydantic import SecretStr

from app.core.config import (
    AppConfig,
    AppEnvironment,
    Auth0Config,
    DatabaseConfig,
    FeatureFlagsConfig,
    LLMConfig,
    ObservabilityConfig,
    SecurityConfig,
    ServerConfig,
    Settings,
    VectorSearchConfig,
    to_asyncpg_url,
    to_libpq_url,
    to_psycopg_url,
)


def test_app_config_defaults():
    config = AppConfig()
    assert config.name == "card-fraud-ops-analyst-agent"
    assert config.env == AppEnvironment.LOCAL
    assert config.version == "0.1.0"


def test_app_config_env_parsing():
    config = AppConfig(env="prod")
    assert config.env == AppEnvironment.PROD


def test_server_config_defaults():
    config = ServerConfig()
    assert config.host == "0.0.0.0"
    assert config.port == 8003


def test_database_config_defaults():
    config = DatabaseConfig()
    assert config.name == "fraud_gov"
    assert config.pool_size == 10


def test_database_config_strips_engine_options_from_url_query():
    config = DatabaseConfig(
        database_url_app=(
            "postgresql://postgres:secret@localhost:5432/fraud_gov"
            "?pool_size=20&max_overflow=10&sslmode=require"
        )
    )
    assert "pool_size=" not in config.async_url
    assert "max_overflow=" not in config.async_url
    assert "sslmode=require" in config.async_url
    assert config.async_url.startswith("postgresql+asyncpg://")


def test_database_config_sync_url_strips_engine_options_from_url_query():
    config = DatabaseConfig(
        database_url_app=(
            "postgresql+asyncpg://postgres:secret@localhost:5432/fraud_gov"
            "?pool_size=20&pool_recycle=1800"
        )
    )
    assert "pool_size=" not in config.sync_url
    assert "pool_recycle=" not in config.sync_url
    assert config.sync_url.startswith("postgresql+psycopg://")


def test_to_asyncpg_url_normalizes_driver_and_strips_engine_options():
    normalized = to_asyncpg_url(
        "postgresql+psycopg://postgres:secret@localhost:5432/fraud_gov"
        "?pool_size=20&max_overflow=10&sslmode=require"
    )
    assert normalized.startswith("postgresql+asyncpg://")
    assert "pool_size=" not in normalized
    assert "max_overflow=" not in normalized
    assert "sslmode=require" in normalized


def test_to_psycopg_url_normalizes_driver_and_strips_engine_options():
    normalized = to_psycopg_url(
        "postgresql+asyncpg://postgres:secret@localhost:5432/fraud_gov"
        "?pool_timeout=30&pool_recycle=1800&sslmode=require"
    )
    assert normalized.startswith("postgresql+psycopg://")
    assert "pool_timeout=" not in normalized
    assert "pool_recycle=" not in normalized
    assert "sslmode=require" in normalized


def test_to_libpq_url_normalizes_sqlalchemy_driver_prefixes():
    normalized = to_libpq_url(
        "postgresql+asyncpg://postgres:secret@localhost:5432/fraud_gov?pool_size=20&sslmode=require"
    )
    assert normalized.startswith("postgresql://")
    assert "pool_size=" not in normalized
    assert "sslmode=require" in normalized


def test_auth0_config_defaults(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_ALGORITHMS", raising=False)
    config = Auth0Config()
    assert config.jwks_url == "https:///.well-known/jwks.json"
    assert config.algorithms_list == ["RS256"]
    assert config.accepted_audiences == ()


def test_auth0_config_accepted_audiences_prefers_user_audience():
    config = Auth0Config(
        audience="https://fraud-ops-analyst-agent-api",
        user_audience="https://fraud-portal-user-api",
    )
    assert config.accepted_audiences == (
        "https://fraud-portal-user-api",
        "https://fraud-ops-analyst-agent-api",
    )


def test_auth0_config_accepted_audiences_falls_back_to_service_audience():
    config = Auth0Config(audience="https://fraud-ops-analyst-agent-api")
    assert config.accepted_audiences == ("https://fraud-ops-analyst-agent-api",)


def test_security_config_defaults(monkeypatch):
    monkeypatch.delenv("SECURITY_SKIP_JWT_VALIDATION", raising=False)
    config = SecurityConfig()
    assert config.skip_jwt_validation is False
    assert "http://localhost:3000" in config.cors_allowed_origins


def test_feature_flags_defaults():
    config = FeatureFlagsConfig()
    assert config.enable_llm_reasoning is True
    assert config.enforce_human_approval is True


def test_vector_search_defaults():
    config = VectorSearchConfig()
    assert config.enabled is True
    assert config.api_base == "https://api.openai.com/v1"


def test_vector_search_rewrites_explicit_localhost_in_container(monkeypatch):
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    monkeypatch.setenv("VECTOR_API_BASE", "http://localhost:11434/api")
    config = VectorSearchConfig()
    assert config.api_base == "http://host.docker.internal:11434/api"


def test_vector_search_keeps_explicit_api_base_in_container(monkeypatch):
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    monkeypatch.setenv("VECTOR_API_BASE", "http://vector-provider:11434/api")
    config = VectorSearchConfig()
    assert config.api_base == "http://vector-provider:11434/api"


def test_vector_search_does_not_inherit_cloud_key_for_local_api_base(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "cloud-key")
    monkeypatch.setenv("VECTOR_API_BASE", "http://host.docker.internal:11434/api")
    config = VectorSearchConfig(api_key=SecretStr(""))
    assert config.api_key.get_secret_value() == ""


def test_vector_search_inherits_cloud_key_for_remote_api_base(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "cloud-key")
    monkeypatch.delenv("VECTOR_API_KEY", raising=False)
    monkeypatch.setenv("VECTOR_API_BASE", "https://api.openai.com/v1")
    config = VectorSearchConfig(api_key=SecretStr(""))
    assert config.api_key.get_secret_value() == "cloud-key"


def test_vector_search_does_not_align_to_llm_base_url_by_default(monkeypatch):
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.delenv("VECTOR_ALIGN_WITH_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    config = VectorSearchConfig()
    # Default api_base (cloud URL) is not rewritten without explicit VECTOR_API_BASE
    assert config.api_base == "https://api.openai.com/v1"


def test_vector_search_aligns_to_llm_base_url_when_enabled(monkeypatch):
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.setenv("VECTOR_ALIGN_WITH_LLM_BASE_URL", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom-llm-provider.com")
    monkeypatch.delenv("OPS_AGENT_DOCKER_RUNTIME", raising=False)
    config = VectorSearchConfig(api_base="http://localhost:11434/api")
    assert config.api_base == "https://custom-llm-provider.com/api"


def test_vector_search_align_recomputes_cloud_key_when_base_becomes_remote(monkeypatch):
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.delenv("VECTOR_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "cloud-key")
    monkeypatch.setenv("VECTOR_ALIGN_WITH_LLM_BASE_URL", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom-llm-provider.com")
    monkeypatch.delenv("OPS_AGENT_DOCKER_RUNTIME", raising=False)

    config = VectorSearchConfig(api_base="http://localhost:11434/api", api_key=SecretStr(""))

    assert config.api_base == "https://custom-llm-provider.com/api"
    assert config.api_key.get_secret_value() == "cloud-key"


def test_observability_config_defaults():
    config = ObservabilityConfig()
    assert config.service_name == "card-fraud-ops-analyst-agent"
    assert config.otlp_endpoint is None


def test_observability_config_exporter_aliases(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", "false")
    config = ObservabilityConfig()
    assert config.otlp_endpoint == "http://jaeger:4317"
    assert config.otlp_insecure is False


def test_settings_composition():
    settings = Settings()
    assert settings.app.name == "card-fraud-ops-analyst-agent"
    assert settings.server.port == 8003
    assert settings.features.enable_llm_reasoning is True


def test_llm_config_rejects_invalid_provider_format():
    with pytest.raises(ValueError, match="provider/model"):
        LLMConfig(provider="gpt-5-mini", base_url="https://api.openai.com/v1")


def test_llm_config_accepts_openai_provider(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config = LLMConfig(provider="openai/gpt-5-mini", base_url="https://api.openai.com/v1")
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key.get_secret_value() == ""


def test_llm_config_adapts_localhost_base_url_in_container(monkeypatch):
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    config = LLMConfig(provider="openai/gpt-5-mini", base_url="http://localhost:11434")
    assert config.base_url == "http://host.docker.internal:11434"
