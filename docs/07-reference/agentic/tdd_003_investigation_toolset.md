# TDD-003: Investigation Toolset

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** ADR-004, ADR-008, ADR-009, TDD-001, TDD-002

---

## 1. Overview

Define the `BaseTool` abstract interface and 6 concrete tools wrapping existing pure logic. Each tool accepts `InvestigationState`, performs one focused analysis, and returns updated state. Pure `*_core.py` logic is preserved under `app/tools/_core/` with zero changes to business logic. The ContextTool uses TM API exclusively (no direct SQL). The ReasoningTool uses LangChain ChatModel.

---

## 2. Base Tool Interface

**File:** `app/tools/base.py`

```python
from abc import ABC, abstractmethod
from app.agent.state import InvestigationState


class BaseTool(ABC):
    """Abstract base class for all investigation tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier used in registry and planner."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description included in planner prompt."""
        ...

    @abstractmethod
    async def execute(self, state: InvestigationState) -> InvestigationState:
        """
        Execute tool logic and return updated state.

        Contract:
        - MUST NOT mutate the input state dict
        - MUST return a new dict with updated fields
        - MUST be deterministic (same input → same output)
        - MUST be idempotent (re-running produces same result)
        - MUST NOT call other tools
        - MUST NOT perform planning decisions
        - MUST NOT directly persist to database
        - SHOULD complete within tool_timeout_seconds (10s default)
        """
        ...
```

---

## 3. Pure Core Logic (Preserved)

These files contain pure, deterministic logic with zero database access. They are moved from `app/agents/*_core.py` to `app/tools/_core/` with **no changes to business logic** — only import paths change.

| Source File | Target File | Key Exports |
|-------------|-------------|-------------|
| `app/agents/context_builder_core.py` | `app/tools/_core/context_logic.py` | `TransactionContext`, `WindowStats`, `Signal`, `compute_window_stats()`, `assemble_context()` |
| `app/agents/pattern_engine_core.py` | `app/tools/_core/pattern_logic.py` | `PatternScore`, `score_amount_anomalies()`, `score_velocity()`, `score_time_anomalies()`, `score_cross_merchant()`, `score_card_testing()` |
| `app/agents/similarity_engine_core.py` | `app/tools/_core/similarity_logic.py` | `SimilarityMatch`, `SimilarityResult`, `freshness_weight()`, `evaluate_similarity()` |
| `app/agents/recommendation_engine_core.py` | `app/tools/_core/recommendation_logic.py` | `RecommendationCandidate`, `generate_recommendations()` |
| `app/agents/reasoning_core.py` | `app/tools/_core/reasoning_logic.py` | `assemble_prompt_payload()`, deterministic fallback logic |
| `app/agents/rule_draft_core.py` | `app/tools/_core/rule_draft_logic.py` | Rule draft generation logic |

### 3.1 Utility Functions (Preserved)

These helper functions support the core logic and are preserved:

| Source File | Target | Disposition |
|-------------|--------|-------------|
| `app/agents/freshness.py` | `app/tools/_core/freshness.py` | Move as-is |
| `app/agents/pattern_utils.py` | `app/tools/_core/pattern_utils.py` | Move as-is |
| `app/agents/similarity_utils.py` | `app/tools/_core/similarity_utils.py` | Move as-is |

### 3.2 Logic to Absorb or Remove

| Source File | Disposition |
|-------------|-------------|
| `app/agents/conflict_matrix.py` | Absorb into PatternTool if useful, otherwise remove |
| `app/agents/evidence_builder.py` | Absorb into individual tools (each tool builds its own evidence) |
| `app/agents/explanation_builder.py` | Absorb into completion node |
| `app/agents/action_planner.py` | Replaced by LLM planner node |
| `app/agents/pipeline.py` | Deleted — replaced by LangGraph graph |

---

## 4. Context Tool

**File:** `app/tools/context_tool.py`

### 4.1 Purpose

Retrieve transaction details and history from Transaction Management API. Enriches `state["context"]`.

### 4.2 Dependencies

- `app/clients/tm_client.py` (new TM API client — see Section 10)

### 4.3 Implementation

```python
class ContextTool(BaseTool):
    name = "context_tool"
    description = "Retrieve transaction details, card history, and merchant context from Transaction Management API"

    def __init__(self, tm_client: TMClient) -> None:
        self._tm_client = tm_client

    async def execute(self, state: InvestigationState) -> InvestigationState:
        transaction_id = state["transaction_id"]

        # 1. Fetch transaction overview (replaces 5 separate SQL queries)
        overview = await self._tm_client.get_transaction_overview(transaction_id)
        transaction = overview["transaction"]

        # 2. Extract identifiers (card_id, not user_id — TM has no user_id column)
        card_id = transaction["card_id"]
        merchant_id = transaction["merchant_id"]

        # 3. Fetch history (parallel — uses card_id, not user_id)
        card_history, merchant_history = await asyncio.gather(
            self._tm_client.get_card_history(card_id, hours_back=72),
            self._tm_client.get_merchant_history(merchant_id, hours_back=72),
        )

        # 4. Enrich via pure logic
        context = context_logic.assemble_context(
            transaction=transaction,
            card_history=card_history,
            merchant_history=merchant_history,
        )

        # 5. Compute window statistics
        for window_hours in [1, 6, 24, 72]:
            window_stats = context_logic.compute_window_stats(
                card_history, window_hours
            )
            context[f"window_{window_hours}h"] = asdict(window_stats)

        return {**state, "context": context}
```

### 4.4 TM API Failure Handling

If TM API calls fail, `ContextTool` raises (tool executor catches and marks as `FAILED`). The planner will see that `context` is still empty and can decide to retry or terminate.

---

## 5. Pattern Tool

**File:** `app/tools/pattern_tool.py`

### 5.1 Purpose

Score fraud patterns (velocity, amount anomalies, card testing, cross-merchant, time anomalies) from transaction context.

### 5.2 Dependencies

None — uses pure logic only from `pattern_logic`.

### 5.3 Implementation

```python
class PatternTool(BaseTool):
    name = "pattern_tool"
    description = "Analyze transaction for fraud patterns: velocity bursts, amount anomalies, card testing, cross-merchant spread, time anomalies"

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        if not context:
            raise ValueError("Context must be populated before pattern analysis")

        transaction = context["transaction"]
        card_history = context.get("card_history", [])
        settings = get_settings()

        # Score each pattern dimension
        scores = []
        scores.append(pattern_logic.score_amount_anomalies(
            transaction, card_history, context.get("window_24h"), settings.scoring
        ))
        scores.append(pattern_logic.score_velocity(
            transaction, card_history, context.get("window_1h"), settings.scoring
        ))
        scores.append(pattern_logic.score_time_anomalies(
            transaction, card_history, settings.scoring
        ))
        scores.append(pattern_logic.score_cross_merchant(
            transaction, card_history, context.get("window_24h"), settings.scoring
        ))
        scores.append(pattern_logic.score_card_testing(
            transaction, card_history, settings.scoring
        ))

        # Aggregate
        pattern_results = {
            "scores": [asdict(s) for s in scores],
            "overall_score": sum(s.score * s.weight for s in scores)
                             / max(sum(s.weight for s in scores), 1),
            "patterns_detected": [s.pattern_name for s in scores if s.score > 0.5],
        }

        # Build evidence
        evidence_entry = {
            "category": "pattern_analysis",
            "tool": "pattern_tool",
            "description": f"Detected {len(pattern_results['patterns_detected'])} fraud patterns",
            "data": pattern_results,
        }

        return {
            **state,
            "pattern_results": pattern_results,
            "evidence": [*state["evidence"], evidence_entry],
        }
```

---

## 6. Similarity Tool

**File:** `app/tools/similarity_tool.py`

### 6.1 Purpose

Find similar past fraud investigations using vector embeddings (pgvector).

### 6.2 Dependencies

- `app/clients/embedding_client.py` (existing — Ollama `/api/embed`)
- Database session for pgvector queries

### 6.3 Implementation

```python
class SimilarityTool(BaseTool):
    name = "similarity_tool"
    description = "Find similar historical fraud investigations using vector similarity search"

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        session: AsyncSession,
    ) -> None:
        self._embedding_client = embedding_client
        self._session = session

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        if not context:
            raise ValueError("Context must be populated before similarity analysis")

        settings = get_settings()
        if not settings.vector_search.enabled:
            return {**state, "similarity_results": {"matches": [], "overall_score": 0.0, "skipped": True}}

        # 1. Generate embedding for current transaction
        embed_text = self._build_embed_text(context)
        embedding_response = await self._embedding_client.embed(embed_text)

        # 2. Query pgvector for nearest neighbors
        similar_rows = await self._query_similar(
            embedding_response.embedding,
            limit=settings.vector_search.search_limit,
            min_similarity=settings.vector_search.min_similarity,
        )

        # 3. Evaluate via pure logic
        result = similarity_logic.evaluate_similarity(
            transaction=context["transaction"],
            similar_transactions=similar_rows,
        )

        # 4. Build evidence
        evidence_entry = {
            "category": "similarity_analysis",
            "tool": "similarity_tool",
            "description": f"Found {len(result.matches)} similar transactions",
            "data": asdict(result),
        }

        return {
            **state,
            "similarity_results": asdict(result),
            "evidence": [*state["evidence"], evidence_entry],
        }

    async def _query_similar(self, embedding, limit, min_similarity):
        """Query ops_agent_transaction_embeddings via pgvector."""
        query = text("""
            SELECT transaction_id, 1 - (embedding <=> :embedding::vector) AS similarity,
                   metadata
            FROM fraud_gov.ops_agent_transaction_embeddings
            WHERE 1 - (embedding <=> :embedding::vector) >= :min_sim
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """)
        result = await self._session.execute(query, {
            "embedding": str(embedding),
            "min_sim": min_similarity,
            "limit": limit,
        })
        return [row_to_dict(r) for r in result.fetchall()]
```

### 6.4 Note on DB Access

This tool requires a DB session for vector queries — this is the ONE exception where a tool accesses the database. The session is injected via constructor, not from state. This is acceptable because pgvector queries are read-only and the `ops_agent_transaction_embeddings` table is owned by this project.

---

## 7. Reasoning Tool

**File:** `app/tools/reasoning_tool.py`

### 7.1 Purpose

LLM-powered fraud reasoning given collected evidence. Produces risk assessment, hypotheses, and explanation.

### 7.2 Dependencies

- LangChain `BaseChatModel` (injected)

### 7.3 Implementation

```python
class ReasoningTool(BaseTool):
    name = "reasoning_tool"
    description = "Perform LLM-powered fraud reasoning based on collected evidence to generate risk assessment and hypotheses"

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        pattern_results = state["pattern_results"]
        similarity_results = state["similarity_results"]

        # 1. Redact PII before sending to LLM
        redacted_context = redaction.redact_context(context)

        # 2. Build reasoning prompt
        prompt_payload = reasoning_logic.assemble_prompt_payload(
            context=redacted_context,
            pattern_results=pattern_results,
            similarity_results=similarity_results,
        )

        # 3. Call LLM
        try:
            messages = [
                SystemMessage(content=REASONING_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(prompt_payload)),
            ]
            response = await self._llm.ainvoke(messages)
            reasoning = json.loads(response.content)
        except Exception:
            # Deterministic fallback
            reasoning = reasoning_logic.deterministic_reasoning(
                pattern_results=pattern_results,
                similarity_results=similarity_results,
            )
            reasoning["llm_status"] = "fallback"

        # 4. Extract hypotheses
        hypotheses = reasoning.get("hypotheses", [])

        # 5. Update severity based on reasoning
        severity = reasoning.get("risk_level", state["severity"])
        confidence = reasoning.get("confidence", state["confidence_score"])

        return {
            **state,
            "reasoning": reasoning,
            "hypotheses": [*state["hypotheses"], *hypotheses],
            "severity": severity,
            "confidence_score": confidence,
        }
```

### 7.4 Deterministic Fallback

If LLM is unavailable or fails, `reasoning_logic.deterministic_reasoning()` produces a rule-based risk assessment:
- Pattern overall_score > 0.7 → HIGH
- Pattern overall_score > 0.4 → MEDIUM
- Otherwise → LOW

No investigation is blocked by LLM unavailability.

---

## 8. Recommendation Tool

**File:** `app/tools/recommendation_tool.py`

### 8.1 Purpose

Generate fraud recommendations based on evidence and reasoning results.

### 8.2 Dependencies

None — uses pure logic only.

### 8.3 Implementation

```python
class RecommendationTool(BaseTool):
    name = "recommendation_tool"
    description = "Generate fraud investigation recommendations based on evidence and reasoning results"

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        pattern_results = state["pattern_results"]
        similarity_results = state["similarity_results"]
        reasoning = state["reasoning"]
        severity = state["severity"]

        # Convert pattern scores back to PatternScore objects
        pattern_scores = [
            pattern_logic.PatternScore(**s)
            for s in pattern_results.get("scores", [])
        ]

        # Convert similarity results
        similarity_result = similarity_logic.SimilarityResult(
            matches=[
                similarity_logic.SimilarityMatch(**m)
                for m in similarity_results.get("matches", [])
            ],
            overall_score=similarity_results.get("overall_score", 0.0),
        )

        # Generate recommendations via pure logic
        candidates = recommendation_logic.generate_recommendations(
            pattern_scores=pattern_scores,
            similarity_result=similarity_result,
            severity=severity,
            context=context,
        )

        recommendations = [asdict(c) for c in candidates]

        return {
            **state,
            "recommendations": recommendations,
        }
```

---

## 9. Rule Draft Tool

**File:** `app/tools/rule_draft_tool.py`

### 9.1 Purpose

Generate a fraud rule draft from recommendations and reasoning.

### 9.2 Dependencies

None — uses pure logic.

### 9.3 Implementation

```python
class RuleDraftTool(BaseTool):
    name = "rule_draft_tool"
    description = "Generate a fraud detection rule draft based on recommendations and investigation evidence"

    async def execute(self, state: InvestigationState) -> InvestigationState:
        recommendations = state["recommendations"]
        reasoning = state["reasoning"]
        context = state["context"]
        pattern_results = state["pattern_results"]

        if not recommendations:
            return {**state, "rule_draft": None}

        rule_draft = rule_draft_logic.generate_rule_draft(
            recommendations=recommendations,
            reasoning=reasoning,
            context=context,
            pattern_results=pattern_results,
        )

        return {**state, "rule_draft": rule_draft}
```

---

## 10. TM API Client

**File:** `app/clients/tm_client.py`

New HTTP client replacing `ContextReader` SQL queries. Follows the same patterns as existing `rule_management_client.py`.

### 10.1 Configuration

Add to `app/core/config.py`:

```python
class TMClientConfig(BaseSettings):
    """Transaction Management API client configuration."""
    model_config = SettingsConfigDict(env_prefix="TM_")

    base_url: str = "http://localhost:8002"
    timeout_seconds: int = 10
    max_retries: int = 3
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout: int = 60
    # M2M auth (required in PROD, empty for local dev)
    m2m_client_id: str = ""
    m2m_client_secret: str = ""
    m2m_audience: str = ""
```

### 10.2 Implementation

```python
class TMClient:
    """Async HTTP client for Transaction Management API.

    Corrected to match actual TM API surface (see TDD-007):
    - Uses /overview endpoint (replaces 5 separate queries)
    - Uses card_id for history (TM has no user_id column)
    - Auto-pagination for history endpoints (max 3 pages)
    """

    def __init__(self, config: TMClientConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None

    async def get_transaction_overview(
        self, transaction_id: str, include_rules: bool = True
    ) -> dict[str, Any]:
        """GET /api/v1/transactions/{transaction_id}/overview

        Returns transaction + review + notes + case + matched_rules in one call.
        Replaces: get_transaction, get_rule_matches, get_reviews, get_notes, get_case.
        """
        params = {"include_rules": str(include_rules).lower()}
        return await self._request(
            "GET", f"/api/v1/transactions/{transaction_id}/overview", params=params
        )

    async def get_card_history(
        self, card_id: str, hours_back: int = 72, max_pages: int = 3
    ) -> list[dict[str, Any]]:
        """GET /api/v1/transactions?card_id=X&from_date=Y with auto-pagination."""
        from_date = (utc_now() - timedelta(hours=hours_back)).isoformat()
        all_items: list[dict] = []
        cursor = None

        for _ in range(max_pages):
            params: dict[str, Any] = {
                "card_id": card_id, "from_date": from_date, "page_size": 500
            }
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/api/v1/transactions", params=params)
            all_items.extend(data["items"])

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return [_remap(item, TRANSACTION_FIELD_MAP) for item in all_items]

    async def get_merchant_history(
        self, merchant_id: str, hours_back: int = 72, max_pages: int = 3
    ) -> list[dict[str, Any]]:
        """GET /api/v1/transactions?merchant_id=X&from_date=Y with auto-pagination."""
        from_date = (utc_now() - timedelta(hours=hours_back)).isoformat()
        all_items: list[dict] = []
        cursor = None

        for _ in range(max_pages):
            params: dict[str, Any] = {
                "merchant_id": merchant_id, "from_date": from_date, "page_size": 500
            }
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/api/v1/transactions", params=params)
            all_items.extend(data["items"])

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return [_remap(item, TRANSACTION_FIELD_MAP) for item in all_items]

    async def health_check(self) -> bool:
        """Check TM API availability (for readiness probe / circuit breaker)."""
        try:
            await self._request("GET", "/api/v1/health")
            return True
        except Exception:
            return False

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        """Make HTTP request with retry, circuit breaker, and tracing."""
        client = await self._get_client()
        headers = get_tracing_headers()
        url = f"{self._config.base_url}{path}"

        response = await client.request(
            method, url, headers=headers, timeout=self._config.timeout_seconds, **kwargs
        )
        response.raise_for_status()
        return response.json()
```

### 10.3 Doppler Secret

Add `TM_BASE_URL` to Doppler configuration:

| Secret | Description | Default |
|--------|-------------|---------|
| `TM_BASE_URL` | Transaction Management API base URL | `http://localhost:8002` |

---

## 11. Tool Summary Matrix

| Tool | File | Pure Logic Source | External Dependencies | State Fields Updated |
|------|------|------------------|----------------------|---------------------|
| `context_tool` | `context_tool.py` | `context_logic.py` | TM API (`tm_client`) | `context` |
| `pattern_tool` | `pattern_tool.py` | `pattern_logic.py` | None | `pattern_results`, `evidence` |
| `similarity_tool` | `similarity_tool.py` | `similarity_logic.py` | Embedding client, pgvector DB | `similarity_results`, `evidence` |
| `reasoning_tool` | `reasoning_tool.py` | `reasoning_logic.py` | LangChain ChatModel | `reasoning`, `hypotheses`, `severity`, `confidence_score` |
| `recommendation_tool` | `recommendation_tool.py` | `recommendation_logic.py` | None | `recommendations` |
| `rule_draft_tool` | `rule_draft_tool.py` | `rule_draft_logic.py` | None | `rule_draft` |

---

## 12. Tool Execution Order (Typical)

The planner dynamically decides, but a typical investigation follows:

```
1. context_tool        → Fetches transaction + history from TM API
2. pattern_tool        → Scores fraud patterns from context
3. similarity_tool     → Finds similar past investigations
4. reasoning_tool      → LLM reasoning over all evidence
5. recommendation_tool → Generates fraud recommendations
6. rule_draft_tool     → Drafts fraud detection rule
```

The planner may vary this based on:
- Confidence threshold reached early → skip remaining analysis
- Similarity results suggest known pattern → skip pattern analysis
- Critical severity detected → fast-track to recommendation

---

## 13. Performance Requirements

| Tool | Target Latency | Notes |
|------|---------------|-------|
| `context_tool` | < 500ms | Depends on TM API (< 50ms × 3 calls + network) |
| `pattern_tool` | < 100ms | Pure computation |
| `similarity_tool` | < 500ms | Embedding generation + pgvector query |
| `reasoning_tool` | < 10s | LLM call (configurable timeout) |
| `recommendation_tool` | < 50ms | Pure computation |
| `rule_draft_tool` | < 50ms | Pure computation |
