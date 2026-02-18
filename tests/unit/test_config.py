"""Unit tests for config module."""

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


def test_security_config_defaults(monkeypatch):
    monkeypatch.delenv("SECURITY_SKIP_JWT_VALIDATION", raising=False)
    config = SecurityConfig()
    assert config.skip_jwt_validation is False
    assert "http://localhost:3000" in config.cors_allowed_origins


def test_feature_flags_defaults():
    config = FeatureFlagsConfig()
    assert config.enable_deterministic_pipeline is True
    assert config.enable_llm_reasoning is True
    assert config.enforce_human_approval is True


def test_vector_search_defaults():
    config = VectorSearchConfig()
    assert config.enabled is True
    assert config.api_base == "http://localhost:11434/api"


def test_vector_search_defaults_use_host_alias_in_container(monkeypatch):
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    config = VectorSearchConfig()
    assert config.api_base == "http://host.docker.internal:11434/api"


def test_vector_search_keeps_explicit_api_base_in_container(monkeypatch):
    monkeypatch.setenv("OPS_AGENT_DOCKER_RUNTIME", "true")
    monkeypatch.setenv("VECTOR_API_BASE", "http://vector-provider:11434/api")
    config = VectorSearchConfig()
    assert config.api_base == "http://vector-provider:11434/api"


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
    assert settings.features.enable_deterministic_pipeline is True


def test_llm_config_does_not_treat_gpt_provider_as_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    config = LLMConfig(provider="gpt-4o-mini", api_key=SecretStr("openai-key"), base_url="")
    assert config.api_key.get_secret_value() == "openai-key"
