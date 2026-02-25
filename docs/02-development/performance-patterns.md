# Performance Patterns

## Overview

This document catalogs performance-critical code patterns in the Card Fraud Ops Analyst Agent. Understanding these patterns is essential for maintaining the reliability targets defined in the architecture:

- P95 investigation <= 30000ms in agentic local/platform E2E
- P95 detail fetch <= 4000ms
- Recommendation generation failure rate < 1% over 1h windows

## Parallel Query Execution

### Pattern: `asyncio.gather()` for concurrent database queries

When building investigation context, multiple independent queries are executed in parallel to reduce total latency.

**Location:** `app/tools/context_tool.py`

```python
# Parallelize independent queries for better performance
queries = [
    self.reader.get_transaction_rule_matches(transaction_id),
    self.reader.get_transaction_reviews(transaction_id),
    self.reader.get_analyst_notes(transaction_id),
    self.reader.get_transaction_case(transaction_id),
]

if card_id:
    queries.append(self.reader.get_card_history(card_id, hours_back=72))
if merchant_id:
    queries.append(self.reader.get_merchant_history(merchant_id, hours_back=72))

# SECURITY: Check for exceptions in gather results to avoid silent failures
results = await asyncio.gather(*queries, return_exceptions=True)
```

**Key considerations:**
- Use `return_exceptions=True` to prevent one failed query from canceling all queries
- Always unwrap results and check for exceptions explicitly
- Only parallelize truly independent queries (no data dependencies)
- Conditional queries (e.g., card history) are added dynamically

**Performance impact:** Parallelizing 6 queries that each take 50ms reduces total time from ~300ms (sequential) to ~50ms (parallel), minus connection overhead.

### Anti-pattern: Sequential independent queries

```python
# BAD - runs queries sequentially, adding latency
rule_matches = await self.reader.get_transaction_rule_matches(transaction_id)
reviews = await self.reader.get_transaction_reviews(transaction_id)
notes = await self.reader.get_analyst_notes(transaction_id)
```

## Settings Caching

### Pattern: `@lru_cache` for settings singleton

Application settings are cached using `@lru_cache` to avoid repeated environment variable reads and validation overhead.

**Location:** `app/core/config.py`

```python
from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
```

**Key characteristics:**
- Settings loaded once per process lifetime
- Subsequent calls return cached instance (zero overhead)
- Cache persists across requests in the same worker process
- Environment variable changes are NOT auto-detected

**When to reload:**
- After Doppler secret updates
- After feature flag changes
- After configuration migrations
- In tests that require different settings per test case

**How to reload:**

```python
from app.core.config import reload_settings

settings = reload_settings()
```

**Important:** Server restart is required for Doppler changes to take effect. The `get_settings()` cache is per-worker, and workers are long-lived processes.

### Anti-pattern: Creating settings per request

```python
# BAD - parses env vars and validates on every request
from app.core.config import Settings

def handler():
    settings = Settings()  # Expensive validation runs every time
```

## Connection Pool Management

### Pattern: SQLAlchemy async engine with pooling

Database connections are pooled to avoid connection overhead on each request.

**Location:** `app/core/database.py`

```python
def create_async_engine(config: DatabaseConfig) -> AsyncEngine:
    engine = sqlalchemy_create_async_engine(
        config.async_url,
        echo=config.echo,
        pool_size=config.pool_size,          # Default: 10
        max_overflow=config.max_overflow,    # Default: 10
        pool_timeout=config.pool_timeout,    # Default: 30s
        pool_recycle=config.pool_recycle,    # Default: 1800s
        pool_pre_ping=True,                  # Test connections before use
        connect_args={
            "server_settings": {
                "timezone": "UTC",
                "statement_timeout": "30000"  # 30s query timeout
            },
        },
    )
    return engine
```

**Pool sizing (default configuration):**
- `pool_size=10`: Base connections kept open
- `max_overflow=10`: Additional connections created under load
- Total per worker: 20 connections max
- With 4 workers: 80 connections max (below server limit of 100)

**Pool behaviors:**
- `pool_timeout=30`: Wait up to 30s for connection before raising error
- `pool_recycle=1800`: Close and recreate connections after 30 minutes (prevents stale connections)
- `pool_pre_ping=True`: Test connection with SELECT 1 before using it (detects closed connections)
- Connections are checked out from pool at session creation, returned when session closes

**Tuning guidelines:**
- Increase `pool_size` if connection checkout is frequent bottleneck
- Decrease `pool_size` if database server hits connection limit
- Keep `(pool_size + max_overflow) * workers < server_max_connections`
- Monitor `pool_recycle` based on database idle connection timeout

**Session lifecycle:**

```python
async with factory() as session:
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    # Connection returned to pool here
```

### Anti-pattern: Creating engine per request

```python
# BAD - new connection pool created every request
engine = create_async_engine(config)
async with engine.connect() as conn:
    ...
await engine.dispose()  # Expensive teardown
```

## JWKS Caching

### Pattern: In-memory JWKS cache with TTL

JWT verification requires fetching JSON Web Key Sets (JWKS) from Auth0. This is cached to avoid network calls on every authentication.

**Location:** `app/core/auth.py`

```python
_jwks_cache: dict[str, Any] | None = None
_cache_time: datetime | None = None
_cache_lock = asyncio.Lock()

async def fetch_jwks() -> dict[str, Any]:
    global _jwks_cache, _cache_time

    settings = get_settings()
    now = datetime.now(UTC)

    async with _cache_lock:
        if _jwks_cache is not None and _cache_time is not None:
            if (now - _cache_time).total_seconds() < settings.auth0.jwks_cache_ttl:
                return _jwks_cache

    jwks_url = settings.auth0.jwks_url
    client = await get_async_http_client()

    try:
        response = await client.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        _cache_time = now
        return _jwks_cache
    except (httpx.HTTPError, httpx.TimeoutException, ConnectionError) as e:
        if _jwks_cache is not None:
            logger.warning("Using stale JWKS cache")
            return _jwks_cache
        raise
```

**Cache behavior:**
- Default TTL: 3600 seconds (1 hour) via `AUTH0_JWKS_CACHE_TTL`
- Cache is global across all requests
- Async lock prevents concurrent fetches (thundering herd prevention)
- On fetch failure, stale cache is used (graceful degradation)
- Authentication continues to work during Auth0 outages using cached keys

**Security considerations:**
- JWKS keys change rarely (typically only during key rotation)
- 1-hour TTL balances performance and security
- Stale cache is acceptable for short Auth0 outages
- Invalid signatures are still caught by JWT verification

### Anti-pattern: Fetching JWKS on every request

```python
# BAD - network call on every authentication
response = await client.get(settings.auth0.jwks_url)
jwks = response.json()
```

## LLM Timeout and Retry Patterns

### Pattern: Configurable timeout and provider routing

LLM calls have configurable timeouts and retry logic to handle transient failures.

**Location:** `app/llm/provider.py`

**Timeout configuration:**

```python
class LLMConfig(BaseSettings):
    timeout: int = Field(default=30)       # Seconds
    max_retries: int = Field(default=1)    # Retry attempts
    stage_timeout_seconds: int = Field(default=20)
```

**LangChain provider configuration:**

```python
def get_chat_model(settings: Settings) -> BaseChatModel:
    model_spec = settings.planner.model_name
    provider, _, model_name = model_spec.partition("/")
    ...
```

**OllamaProvider (explicit timeout):**

```python
async def complete(self, messages: list[dict[str, str]], **kwargs):
    timeout_s = kwargs.pop("timeout", self.config.timeout)

    timeout = httpx.Timeout(float(timeout_s))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
```

**Timeout behaviors:**
- Default 30-second timeout per LLM call
- Timeout applies to HTTP connection + response time
- `httpx.Timeout` raises `TimeoutException` on expiry
- Retry strategy should be applied at tool/service boundaries for transient failures

**Retry patterns:**
- Implement retry at service layer, not provider layer
- Use exponential backoff for transient failures (503, timeout)
- Do not retry for permanent errors (400, 401, 403)
- Log all retries with warning level

**Example service-level retry:**

```python
# Recommended pattern for calling LLM with retries
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def call_llm_with_retry(messages: list[dict[str, str]]):
    return await llm_provider.complete(messages)
```

### Anti-pattern: No timeout on LLM calls

```python
# BAD - can hang indefinitely on slow LLM
response = await client.post(url, json=payload)
```

## Best Practices

### 1. Use async comprehensions for memory efficiency

```python
# GOOD - generator comprehension, lazy evaluation
results = [await process_item(item) async for item in async_iterator]

# BAD - builds list in memory first
items = [item async for item in async_iterator]
results = [await process_item(item) for item in items]
```

### 2. Batch database operations when possible

```python
# GOOD - single query with IN clause
results = await session.execute(
    select(Transaction).where(Transaction.id.in_(transaction_ids))
)

# BAD - N+1 queries
for txn_id in transaction_ids:
    result = await session.execute(
        select(Transaction).where(Transaction.id == txn_id)
    )
```

### 3. Use connection sessions efficiently

```python
# GOOD - reuse session across related operations
async with get_session() as session:
    context = await build_context(session, txn_id)
    insights = await generate_insights(session, context)

# BAD - creates new session for each operation
context = await build_context(await get_session(), txn_id)
insights = await generate_insights(await get_session(), context)
```

### 4. Set appropriate timeouts on external calls

```python
# GOOD - explicit timeout
timeout = httpx.Timeout(10.0, connect=5.0)
async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.get(url)

# BAD - no timeout, can hang indefinitely
async with httpx.AsyncClient() as client:
    response = await client.get(url)
```

### 5. Monitor performance with OpenTelemetry

```python
# GOOD - automatic tracing via OpenTelemetry instrumentation
# See app/core/metrics.py for automatic span creation

# Manual spans for complex operations
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_investigation(txn_id: str):
    with tracer.start_as_current_span("process_investigation"):
        ...
```

## Anti-Patterns

### 1. Synchronous I/O in async functions

```python
# BAD - blocks event loop
import time
time.sleep(1)  # Blocks entire worker

# GOOD - non-blocking
import asyncio
await asyncio.sleep(1)
```

### 2. Creating database engines per request

```python
# BAD - expensive initialization, pool overhead
engine = create_async_engine(config)
session = AsyncSession(engine)
```

### 3. Not closing HTTP clients

```python
# BAD - resource leak
client = httpx.AsyncClient()
response = await client.get(url)
# Never closed - sockets stay open

# GOOD - use context manager
async with httpx.AsyncClient() as client:
    response = await client.get(url)
```

### 4. Parallelizing dependent queries

```python
# BAD - race condition, second query needs first query result
results = await asyncio.gather(
    get_transaction(txn_id),
    get_rule_matches(results[0].id),  # results not available yet
)
```

### 5. Ignoring exception handling in gather

```python
# BAD - silent failures, exceptions lost
results = await asyncio.gather(*queries)
for result in results:
    process(result)  # Crash if result is Exception

# GOOD - check for exceptions
results = await asyncio.gather(*queries, return_exceptions=True)
for result in results:
    if isinstance(result, Exception):
        logger.error("Query failed", exc_info=result)
        continue
    process(result)
```

## Performance Monitoring

### Key metrics to track

1. **Database latency:** P50, P95, P99 query execution time
2. **LLM latency:** Time to first token, total generation time
3. **Connection pool utilization:** Active connections vs pool size
4. **JWKS cache hit rate:** Cache hits vs total authentication attempts
5. **Request duration:** End-to-end investigation time by phase

### OpenTelemetry instrumentation

The service automatically emits traces for:
- HTTP requests (FastAPI auto-instrumentation)
- Database queries (SQLAlchemy instrumentation)
- LLM calls (manual spans in planner/reasoning tools)

View traces in Jaeger UI: `http://localhost:16686`

### Performance baseline targets

- Context build: < 100ms (6 parallel queries)
- Pattern engine: < 50ms (in-memory scoring)
- Similarity search: < 200ms (vector search with index)
- LLM reasoning: < 5000ms (model-dependent)
- Recommendation generation: < 100ms (policy checks)

Total deep investigation target: < 8 seconds (all phases)
