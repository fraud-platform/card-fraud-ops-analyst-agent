"""Configuration management for the Ops Analyst Agent service.

Configuration is loaded from environment variables with secrets
managed through Doppler.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

POSTGRESQL_PREFIX = "postgresql://"
ASYNCPG_DRIVER = "+asyncpg"
PSYCPG_DRIVER = "+psycopg"
ENGINE_OPTION_QUERY_KEYS = frozenset({"pool_size", "max_overflow", "pool_timeout", "pool_recycle"})


def _is_running_in_container() -> bool:
    """Best-effort detection for Docker/containerized runtime."""
    explicit = os.getenv("OPS_AGENT_DOCKER_RUNTIME", "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    return os.path.exists("/.dockerenv")


def _strip_engine_query_params(url: str) -> str:
    """Strip SQLAlchemy engine options accidentally passed in DATABASE_URL query args."""
    if "?" not in url:
        return url

    parsed = urlsplit(url)
    if not parsed.query:
        return url

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in ENGINE_OPTION_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(filtered_query, doseq=True),
            parsed.fragment,
        )
    )


def normalize_database_url(url: str) -> str:
    """Normalize a DB URL by stripping SQLAlchemy engine-only query params."""
    return _strip_engine_query_params(url.strip())


def to_asyncpg_url(url: str) -> str:
    """Return a SQLAlchemy URL compatible with the asyncpg dialect."""
    normalized = normalize_database_url(url)
    if normalized.startswith(f"postgresql{PSYCPG_DRIVER}://"):
        return normalized.replace(PSYCPG_DRIVER, ASYNCPG_DRIVER, 1)
    if normalized.startswith(POSTGRESQL_PREFIX) and ASYNCPG_DRIVER not in normalized:
        new_prefix = POSTGRESQL_PREFIX.removesuffix("://") + ASYNCPG_DRIVER + "://"
        return normalized.replace(POSTGRESQL_PREFIX, new_prefix, 1)
    return normalized


def to_psycopg_url(url: str) -> str:
    """Return a SQLAlchemy URL compatible with the psycopg dialect."""
    normalized = normalize_database_url(url)
    if normalized.startswith(f"postgresql{ASYNCPG_DRIVER}://"):
        return normalized.replace(ASYNCPG_DRIVER, PSYCPG_DRIVER, 1)
    if normalized.startswith(POSTGRESQL_PREFIX):
        return normalized.replace(POSTGRESQL_PREFIX, f"postgresql{PSYCPG_DRIVER}://", 1)
    return normalized


def to_libpq_url(url: str) -> str:
    """Return a libpq/psycopg-native URL (postgresql://...)."""
    normalized = normalize_database_url(url)
    if normalized.startswith(f"postgresql{ASYNCPG_DRIVER}://"):
        return normalized.replace(f"postgresql{ASYNCPG_DRIVER}://", POSTGRESQL_PREFIX, 1)
    if normalized.startswith(f"postgresql{PSYCPG_DRIVER}://"):
        return normalized.replace(f"postgresql{PSYCPG_DRIVER}://", POSTGRESQL_PREFIX, 1)
    return normalized


class AppEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PROD = "prod"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AppConfig(BaseSettings):
    name: str = Field(default="card-fraud-ops-analyst-agent")
    env: AppEnvironment = Field(default=AppEnvironment.LOCAL)
    version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    api_prefix: str = Field(default="/api/v1")

    model_config = SettingsConfigDict(env_prefix="APP_")

    @field_validator("env", mode="before")
    @classmethod
    def validate_env(cls, v: str | AppEnvironment) -> AppEnvironment:
        if isinstance(v, AppEnvironment):
            return v
        return AppEnvironment(v)

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str | LogLevel) -> LogLevel:
        if isinstance(v, LogLevel):
            return v
        return LogLevel(v)


class ServerConfig(BaseSettings):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8003)
    workers: int = Field(default=4)
    max_connections: int = Field(default=100)
    keepalive_timeout: int = Field(default=5)

    model_config = SettingsConfigDict(env_prefix="SERVER_")


class DatabaseConfig(BaseSettings):
    url_app: str = Field(default="", alias="database_url_app")
    url_admin: str = Field(default="", alias="database_url_admin")

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="fraud_gov")
    user: str = Field(default="postgres")
    password: SecretStr = Field(default=SecretStr(""))
    pool_size: int = Field(default=10)
    max_overflow: int = Field(
        default=10
    )  # Reduced from 20 - with 4 workers, total=80 < server limit of 100
    pool_timeout: int = Field(default=30)
    pool_recycle: int = Field(default=1800)
    echo: bool = Field(default=False)
    require_ssl: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        populate_by_name=True,
    )

    @property
    def async_url(self) -> str:
        if self.url_app:
            return to_asyncpg_url(self.url_app)
        password = self.password.get_secret_value()
        return f"postgresql{ASYNCPG_DRIVER}://{self.user}:{password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        if self.url_app:
            return to_psycopg_url(self.url_app)
        password = self.password.get_secret_value()
        return f"postgresql+psycopg://{self.user}:{password}@{self.host}:{self.port}/{self.name}"


class Auth0Config(BaseSettings):
    domain: str = Field(default="")
    audience: str = Field(default="")
    client_id: str = Field(default="")
    client_secret: SecretStr = Field(default=SecretStr(""))
    algorithms: str = Field(default="RS256")
    issuer: str | None = Field(default=None)
    jwks_cache_ttl: int = Field(default=3600)  # 1 hour for stable tenants

    model_config = SettingsConfigDict(env_prefix="AUTH0_")

    @property
    def jwks_url(self) -> str:
        return f"https://{self.domain}/.well-known/jwks.json"

    @property
    def issuer_url(self) -> str:
        return f"https://{self.domain}/"

    @property
    def algorithms_list(self) -> list[str]:
        return [algo.strip() for algo in self.algorithms.split(",")]


class SecurityConfig(BaseSettings):
    cors_allowed_origins: str = Field(default="http://localhost:3000,http://localhost:8000")
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: list[str] = Field(default=["GET", "POST", "PATCH", "DELETE", "PUT"])
    cors_allow_headers: list[str] = Field(default=["Authorization", "Content-Type", "X-Request-ID"])
    sanitize_errors: bool = Field(default=True)
    skip_jwt_validation: bool = Field(default=False)
    expose_ready_features: bool = Field(default=False)
    max_request_size_bytes: int = Field(default=1_048_576)
    max_response_size_bytes: int = Field(default=2_097_152)

    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    @field_validator("cors_allowed_origins", mode="after")
    @classmethod
    def validate_cors_allowed_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            origins = [origin.strip() for origin in v.split(",") if origin.strip()]
            return origins
        return v

    @field_validator("skip_jwt_validation", mode="before")
    @classmethod
    def parse_skip_jwt_validation(cls, v: bool | str) -> bool:
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v


class ObservabilityConfig(BaseSettings):
    service_name: str = Field(default="card-fraud-ops-analyst-agent")
    otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("exporter_otlp_endpoint", "otlp_endpoint"),
    )
    otlp_insecure: bool = Field(
        default=True,
        validation_alias=AliasChoices("exporter_otlp_insecure", "otlp_insecure"),
    )
    traces_sampler: str = Field(default="always_on")
    metrics_export_interval: int = Field(default=60000)
    log_record_format: str = Field(default="json")

    model_config = SettingsConfigDict(env_prefix="OTEL_")

    @model_validator(mode="after")
    def apply_exporter_env_fallbacks(self) -> ObservabilityConfig:
        """Support standard OpenTelemetry env names used in container orchestration."""
        if not self.otlp_endpoint:
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_OTLP_ENDPOINT")
            if endpoint:
                self.otlp_endpoint = endpoint

        insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE")
        if insecure is not None:
            self.otlp_insecure = insecure.strip().lower() in {"1", "true", "yes", "on"}

        return self


class FeatureFlagsConfig(BaseSettings):
    enable_llm_reasoning: bool = Field(default=True)
    enable_rule_draft_export: bool = Field(default=False)
    enforce_human_approval: bool = Field(default=True)
    rule_management_base_url: str = Field(default="")

    model_config = SettingsConfigDict(env_prefix="OPS_AGENT_")


class ScoringConfig(BaseSettings):
    """Configurable scoring thresholds for fraud pattern detection."""

    velocity_burst_1h_threshold: int = Field(default=10)
    velocity_burst_6h_threshold: int = Field(default=20)
    velocity_burst_1h_score: float = Field(default=0.9)
    velocity_burst_6h_score: float = Field(default=0.8)

    decline_ratio_high_threshold: float = Field(default=0.5)
    decline_ratio_medium_threshold: float = Field(default=0.3)

    cross_merchant_high_threshold: int = Field(default=10)
    cross_merchant_medium_threshold: int = Field(default=5)

    amount_round_numbers: list[int] = Field(
        default=[100, 200, 300, 400, 500, 750, 1000, 1500, 2000, 5000, 10000]
    )
    amount_high_threshold: float = Field(default=1000)
    amount_elevated_threshold: float = Field(default=500)
    amount_zscore_outlier_threshold: float = Field(default=3.0)
    amount_zscore_warning_threshold: float = Field(default=2.0)
    amount_spike_threshold: float = Field(default=3.0)

    time_unusual_hours: list[int] = Field(default=[0, 1, 2, 3, 4, 5])
    time_unusual_hour_score: float = Field(default=0.7)
    time_high_risk_combo_score: float = Field(default=0.8)
    time_timezone_mismatch_score: float = Field(default=0.9)

    severity_critical_threshold: float = Field(default=0.7)
    severity_high_threshold: float = Field(default=0.5)
    severity_medium_threshold: float = Field(default=0.3)

    model_config = SettingsConfigDict(env_prefix="SCORING_")


class VectorSearchConfig(BaseSettings):
    """Vector similarity search configuration.

    This is intentionally separate from FeatureFlagsConfig.
    The kill switch is `VECTOR_ENABLED`.
    """

    enabled: bool = Field(default=True)
    model_name: str = Field(default="mxbai-embed-large")
    api_base: str = Field(default="http://localhost:11434/api")
    api_key: SecretStr = Field(default=SecretStr(""))
    dimension: int = Field(default=1024)
    search_limit: int = Field(default=20)
    time_window_days: int = Field(default=90)
    min_similarity: float = Field(default=0.3)
    request_timeout_s: float = Field(default=10.0)
    retry_attempts: int = Field(default=3)
    retry_backoff_seconds: float = Field(default=0.25)

    model_config = SettingsConfigDict(env_prefix="VECTOR_")

    @model_validator(mode="after")
    def fill_ollama_api_key(self) -> VectorSearchConfig:
        if not self.api_key.get_secret_value():
            ollama_key = os.getenv("OLLAMA_API_KEY", "")
            if ollama_key:
                self.api_key = SecretStr(ollama_key)
        return self

    @model_validator(mode="after")
    def adapt_localhost_for_container_runtime(self) -> VectorSearchConfig:
        """Use host alias when vector base is localhost inside a container."""
        if os.getenv("VECTOR_API_BASE"):
            return self
        api_base = self.api_base.strip()
        if _is_running_in_container():
            if api_base.startswith("http://localhost:"):
                self.api_base = api_base.replace(
                    "http://localhost:",
                    "http://host.docker.internal:",
                    1,
                )
            elif api_base.startswith("https://localhost:"):
                self.api_base = api_base.replace(
                    "https://localhost:",
                    "https://host.docker.internal:",
                    1,
                )
        return self


class LLMConfig(BaseSettings):
    provider: str = Field(default="ollama/gpt-oss:20b")
    base_url: str = Field(default="https://ollama.com")
    api_key: SecretStr = Field(default=SecretStr(""))
    timeout: int = Field(default=30)
    max_retries: int = Field(default=1)
    stage_timeout_seconds: int = Field(default=20)
    prompt_guard_enabled: bool = Field(default=True)
    max_prompt_tokens: int = Field(default=4000)
    max_completion_tokens: int = Field(default=384)
    consistency_threshold: float = Field(default=0.7)

    model_config = SettingsConfigDict(env_prefix="LLM_")

    @model_validator(mode="after")
    def enforce_ollama_cloud_only(self) -> LLMConfig:
        if not self.provider.startswith(("ollama/", "ollama_chat/")):
            raise ValueError(
                "LLM_PROVIDER must be an Ollama model (prefix ollama/ or ollama_chat/)."
            )

        base_url = self.base_url.strip()
        if not base_url:
            raise ValueError("LLM_BASE_URL is required and must point to Ollama Cloud.")

        lower = base_url.lower()
        if "localhost" in lower or "127.0.0.1" in lower:
            raise ValueError(
                "LLM_BASE_URL cannot be localhost for reasoning/planner. Use Ollama Cloud endpoint."
            )
        if "ollama.com" not in lower:
            raise ValueError("LLM_BASE_URL must target Ollama Cloud (https://ollama.com).")

        if not self.api_key.get_secret_value():
            ollama_key = os.getenv("OLLAMA_API_KEY", "")
            if ollama_key:
                self.api_key = SecretStr(ollama_key)
        return self


class LangGraphConfig(BaseSettings):
    max_steps: int = Field(default=20)
    investigation_timeout_seconds: int = Field(default=120)
    tool_timeout_seconds: int = Field(default=30)
    planner_timeout_seconds: int = Field(default=10)

    model_config = SettingsConfigDict(env_prefix="LANGGRAPH_")


class PlannerConfig(BaseSettings):
    llm_enabled: bool = Field(default=True)
    model_name: str = Field(default="ollama/gpt-oss:20b")
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=256)
    timeout_seconds: int = Field(default=10)

    model_config = SettingsConfigDict(env_prefix="PLANNER_")


class TMClientConfig(BaseSettings):
    base_url: str = Field(default="http://localhost:8002")
    timeout_seconds: float = Field(default=10.0)
    retry_count: int = Field(default=3)
    circuit_breaker_threshold: int = Field(default=5)
    circuit_breaker_timeout: int = Field(default=60)
    m2m_client_id: str = Field(default="")
    m2m_client_secret: SecretStr = Field(default=SecretStr(""))
    m2m_audience: str = Field(default="")

    model_config = SettingsConfigDict(env_prefix="TM_")

    @model_validator(mode="after")
    def adapt_localhost_for_container_runtime(self) -> TMClientConfig:
        """Use Docker service hostname when TM base URL is localhost inside a container.

        TM runs as a sibling container named 'transaction-management' in the platform
        Docker network. Localhost from inside the ops-agent container doesn't reach TM.
        """
        if os.getenv("TM_BASE_URL"):
            return self
        if _is_running_in_container() and self.base_url.startswith("http://localhost:"):
            self.base_url = self.base_url.replace(
                "http://localhost:", "http://transaction-management:", 1
            )
        return self


class Settings(BaseSettings):
    app: AppConfig = Field(default_factory=AppConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth0: Auth0Config = Field(default_factory=Auth0Config)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    features: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    vector_search: VectorSearchConfig = Field(default_factory=VectorSearchConfig)
    langgraph: LangGraphConfig = Field(default_factory=LangGraphConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    tm_client: TMClientConfig = Field(default_factory=TMClientConfig)
    metrics_token: str | None = Field(default=None)

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if self.security.skip_jwt_validation and self.app.env != AppEnvironment.LOCAL:
            raise ValueError(
                "SECURITY_SKIP_JWT_VALIDATION can only be set in local environment. "
                f"Current environment: {self.app.env.value}"
            )
        if self.app.env == AppEnvironment.PROD and not self.features.enforce_human_approval:
            raise ValueError("Human approval enforcement must be enabled in production environment")
        if self.app.env == AppEnvironment.PROD and self.observability.otlp_insecure:
            raise ValueError("OTLP insecure mode is not allowed in production")
        if self.app.env == AppEnvironment.PROD and not self.tm_client.m2m_client_id:
            raise ValueError("TM_M2M_CLIENT_ID required in PROD")
        if (
            self.app.env == AppEnvironment.PROD
            and not self.tm_client.m2m_client_secret.get_secret_value()
        ):
            raise ValueError("TM_M2M_CLIENT_SECRET required in PROD")
        if self.app.env == AppEnvironment.PROD and self.planner.temperature > 0.3:
            raise ValueError("Planner temperature must be <= 0.3 in PROD for consistent behavior")
        if self.planner.model_name != self.llm.provider:
            raise ValueError(
                "PLANNER_MODEL_NAME must match LLM_PROVIDER to prevent provider/model mismatch."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
