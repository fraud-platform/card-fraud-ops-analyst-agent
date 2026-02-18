# ADR 0009: LLM Provider Abstraction

## Status

Accepted

## Context

The Card Fraud Ops Analyst Agent requires Large Language Model (LLM) integration for generating investigation narratives and recommendations. Several constraints and requirements exist:

1. **Multi-environment support**: Development environments may use local LLMs (Ollama) for cost and privacy, while production uses cloud providers (Anthropic, OpenAI) for reliability and performance.

2. **Fallback requirements**: If the primary LLM provider fails or times out, the system should gracefully fall back to deterministic reasoning or an alternative LLM provider.

3. **Provider diversity**: Different teams and environments may prefer different LLM providers (Ollama, Anthropic, OpenAI, Azure, etc.).

4. **Cost optimization**: Local development should not incur cloud API costs. Production should use the most cost-effective provider for each use case.

5. **Rate limiting and quotas**: Cloud providers have rate limits and quotas. A single provider dependency creates a single point of failure.

6. **Future-proofing**: New LLM providers and models are rapidly emerging. The architecture should accommodate new providers without major refactoring.

## Decision

Adopt an abstract LLM provider interface with pluggable implementations:

1. **Abstract `LLMProvider` interface** (`app/llm/provider.py`):
   - `complete()` method for synchronous completion
   - `acomplete()` method for asynchronous completion
   - `json_mode` parameter for structured output
   - Standardized error handling

2. **LiteLLM provider** (`app/llm/provider.py` with `LLMProvider` class):
   - Uses LiteLLM library for 100+ provider support
   - Production default: `anthropic/claude-sonnet-4-5-20250929`
   - Fallback model: `ollama/llama3.2` for local development
   - Configurable via `LLM_PROVIDER` environment variable
   - Supports retry logic, timeouts, and API key management

3. **Ollama provider** (`app/llm/ollama_provider.py` - future):
   - Direct Ollama integration without LiteLLM overhead
   - Optimized for local development and testing
   - Supports JSON mode with `format="json"` parameter

4. **Provider selection logic**:
   ```python
   if LLM_PROVIDER.startswith("ollama/"):
       return OllamaProvider(config)
   else:
       return LiteLLMProvider(config)
   ```

## Alternatives Considered

### Alternative 1: Single Provider (Anthropic only)

**Pros:**
- Simpler implementation
- Single SDK to learn and maintain
- Consistent API across environments

**Cons:**
- No fallback if Anthropic API is down
- Cloud API costs for local development
- Vendor lock-in
- No flexibility to use better/cheaper models

### Alternative 2: External LLM Gateway (e.g., Portkey, Helicone)

**Pros:**
- Provider-agnostic API
- Built-in rate limiting and caching
- Centralized API key management
- Observability and analytics

**Cons:**
- Additional infrastructure dependency
- Additional latency (proxy hop)
- External service cost
- Single point of failure if gateway is down
- More complex deployment architecture

### Alternative 3: Direct SDK Integration per Provider

**Pros:**
- Optimal performance (no abstraction overhead)
- Access to provider-specific features

**Cons:**
- Code explosion (multiple provider implementations)
- Complex conditional logic
- Hard to add new providers
- Inconsistent error handling

## Consequences

### Positive

1. **Fallback support**: Can fall back from cloud provider to local Ollama if API fails
2. **Cost optimization**: Local development uses free local models, production uses cloud
3. **Provider flexibility**: Easy to switch between Anthropic, OpenAI, Azure, etc. via environment variable
4. **Testing support**: Unit tests can mock `LLMProvider` interface, E2E tests can use Ollama
5. **Future-proof**: Adding new provider requires only implementing the interface
6. **Graceful degradation**: Can fall back to deterministic mode if all LLM providers fail

### Negative

1. **Abstraction complexity**: Additional layer of indirection to maintain
2. **Testing burden**: Need to test multiple provider code paths
3. **Least common denominator**: May not support provider-specific features
4. **Dependency on LiteLLM**: LiteLLM library version updates may introduce breaking changes
5. **Configuration drift**: Different environments may have different LLM behavior

### Mitigation Strategies

1. **Comprehensive testing**: Unit tests with mocked providers, E2E tests with real Ollama
2. **Feature flag control**: `OPS_AGENT_ENABLE_LLM_REASONING` to disable LLM entirely if needed
3. **Deterministic fallback**: System always has deterministic mode as safe fallback
4. **LiteLLM version pinning**: Pin to `>=1.78.0,<2.0` to prevent breaking changes
5. **Provider documentation**: Document supported providers and configuration in ops runbooks

## Implementation

### Configuration Example

```bash
# Production (Anthropic Claude Sonnet)
LLM_PROVIDER=anthropic/claude-sonnet-4-5-20250929
LLM_BASE_URL=https://api.anthropic.com
LLM_API_KEY=sk-ant-...
LLM_TIMEOUT=30
LLM_MAX_RETRIES=3
LLM_FALLBACK_MODEL=ollama/llama3.2

# Local Development (Ollama)
LLM_PROVIDER=ollama_chat/llama3.2
LLM_BASE_URL=http://localhost:11434
LLM_API_KEY=ollama
LLM_TIMEOUT=30

# Test Environment (Deterministic only)
OPS_AGENT_ENABLE_LLM_REASONING=false
```

### Code Example

```python
from app.llm.provider import LLMProvider, create_llm_provider

# Create provider based on configuration
provider = create_llm_provider(get_settings().llm)

# Use async completion
response = await provider.acomplete(
    prompt="Analyze this transaction for fraud patterns...",
    json_mode=True
)

# Fallback handling
try:
    response = await provider.acomplete(prompt)
except LLMProviderError as e:
    logger.warning(f"LLM provider failed: {e}, falling back to deterministic")
    # Fall back to deterministic reasoning
```

## Related Decisions

- [ADR 0007: Dual LLM Provider, Cloud Default, Local Fallback](./0007-dual-llm-provider-cloud-default-local-fallback.md)
- [ADR 0004: Hybrid Deterministic Plus LLM Pipeline](./0004-hybrid-deterministic-plus-llm-pipeline.md)
- [ADR 0008: Rollout Gating and SLO Policy](./0008-rollout-gating-and-slo-policy.md)

## References

- LiteLLM Documentation: https://docs.litellm.ai/
- Ollama Documentation: https://github.com/ollama/ollama
- Anthropic API: https://docs.anthropic.com/
