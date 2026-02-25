# TDD-005: API, Services & Schemas

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** ADR-001, ADR-002, TDD-001, TDD-002, TDD-004

---

## 1. Overview

Simplify the API surface. The investigation endpoint invokes the LangGraph graph and returns the agentic trace. The service layer becomes a thin wrapper around graph invocation. Schemas evolve to expose planner decisions, tool executions, and state progression. LLM access shifts from LiteLLM to LangChain ChatModel.

---

## 2. API Route Changes

### 2.1 Endpoints

| Method | Path | Change | Auth Scope |
|--------|------|--------|------------|
| `POST` | `/api/v1/ops-agent/investigations/run` | **REWRITTEN** — invokes LangGraph | `ops_agent:run` |
| `GET` | `/api/v1/ops-agent/investigations/{id}` | **REWRITTEN** — returns full agentic trace | `ops_agent:read` |
| `POST` | `/api/v1/ops-agent/investigations/{id}/resume` | **NEW** — resume failed investigation | `ops_agent:run` |
| `GET` | `/api/v1/ops-agent/worklist/recommendations` | **PRESERVED** | `ops_agent:read` |
| `POST` | `/api/v1/ops-agent/worklist/recommendations/{id}/acknowledge` | **PRESERVED** | `ops_agent:ack` |
| `GET` | `/api/v1/health` | **PRESERVED** | None |
| `GET` | `/api/v1/health/ready` | **PRESERVED** | None |
| `GET` | `/api/v1/health/live` | **PRESERVED** | None |
| `GET` | `/api/v1/metrics` | **PRESERVED** | Token-based |

### 2.2 Removed Endpoints

| Method | Path | Reason |
|--------|------|--------|
| `GET` | `/api/v1/ops-agent/transactions/{txn_id}/insights` | Insights are part of investigation response |
| `POST` | `/api/v1/ops-agent/rule-drafts` | Rule drafts generated as part of investigation |
| `POST` | `/api/v1/ops-agent/rule-drafts/{id}/export` | Move to recommendation acknowledge flow or keep as separate endpoint if needed |

---

## 3. Request/Response Contracts

### 3.1 POST `/investigations/run`

**Request:**

```json
{
  "transaction_id": "txn_abc123",
  "mode": "FULL"
}
```

**Response (200 OK):**

```json
{
  "investigation_id": "01958a3b-...",
  "transaction_id": "txn_abc123",
  "status": "COMPLETED",
  "severity": "HIGH",
  "confidence_score": 0.87,
  "step_count": 6,
  "max_steps": 20,
  "planner_decisions": [
    {
      "step": 1,
      "selected_tool": "context_tool",
      "reason": "Need transaction context before any analysis",
      "confidence": 0.99,
      "timestamp": "2026-02-19T10:00:01Z"
    },
    {
      "step": 2,
      "selected_tool": "pattern_tool",
      "reason": "Analyze fraud patterns from transaction context",
      "confidence": 0.92,
      "timestamp": "2026-02-19T10:00:01.5Z"
    },
    {
      "step": 3,
      "selected_tool": "similarity_tool",
      "reason": "Find similar historical investigations",
      "confidence": 0.88,
      "timestamp": "2026-02-19T10:00:02Z"
    },
    {
      "step": 4,
      "selected_tool": "reasoning_tool",
      "reason": "Sufficient evidence collected, perform risk reasoning",
      "confidence": 0.95,
      "timestamp": "2026-02-19T10:00:03Z"
    },
    {
      "step": 5,
      "selected_tool": "recommendation_tool",
      "reason": "Generate recommendations from reasoning results",
      "confidence": 0.93,
      "timestamp": "2026-02-19T10:00:13Z"
    },
    {
      "step": 6,
      "selected_tool": "COMPLETE",
      "reason": "Investigation complete with recommendations generated",
      "confidence": 0.96,
      "timestamp": "2026-02-19T10:00:13.1Z"
    }
  ],
  "tool_executions": [
    {
      "tool_name": "context_tool",
      "execution_time_ms": 345,
      "status": "SUCCESS",
      "timestamp": "2026-02-19T10:00:01Z"
    },
    {
      "tool_name": "pattern_tool",
      "execution_time_ms": 12,
      "status": "SUCCESS",
      "timestamp": "2026-02-19T10:00:01.5Z"
    }
  ],
  "recommendations": [
    {
      "type": "review_priority",
      "priority": 1,
      "title": "Escalate for immediate review",
      "impact": "Potential card testing pattern detected"
    }
  ],
  "started_at": "2026-02-19T10:00:00Z",
  "completed_at": "2026-02-19T10:00:14Z",
  "total_duration_ms": 14000
}
```

### 3.2 GET `/investigations/{id}`

**Response (200 OK):**

Full investigation detail including all state fields:

```json
{
  "investigation_id": "01958a3b-...",
  "transaction_id": "txn_abc123",
  "status": "COMPLETED",
  "severity": "HIGH",
  "confidence_score": 0.87,
  "step_count": 6,

  "context": {
    "transaction": { "..." : "..." },
    "card_history": [ "..." ],
    "merchant_profile": { "..." },
    "window_1h": { "..." },
    "window_24h": { "..." }
  },

  "evidence": [
    {
      "category": "pattern_analysis",
      "tool": "pattern_tool",
      "description": "Detected 2 fraud patterns",
      "data": { "..." }
    },
    {
      "category": "similarity_analysis",
      "tool": "similarity_tool",
      "description": "Found 3 similar transactions",
      "data": { "..." }
    }
  ],

  "pattern_results": { "..." },
  "similarity_results": { "..." },
  "reasoning": {
    "risk_level": "HIGH",
    "explanation": "Transaction shows card testing pattern...",
    "hypotheses": ["Card testing attack", "Compromised card"],
    "confidence": 0.87
  },

  "recommendations": [ "..." ],
  "rule_draft": { "..." },

  "planner_decisions": [ "..." ],
  "tool_executions": [ "..." ],

  "started_at": "2026-02-19T10:00:00Z",
  "completed_at": "2026-02-19T10:00:14Z"
}
```

### 3.3 POST `/investigations/{id}/resume`

**Request:** Empty body (state loaded from DB)

**Response:** Same shape as `/investigations/run`

---

## 4. Pydantic Schemas

**File:** `app/schemas/v1/investigations.py`

```python
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Request to start a new investigation."""
    transaction_id: str
    mode: str = "FULL"


class PlannerDecisionSchema(BaseModel):
    """Record of a planner decision."""
    step: int
    selected_tool: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: str


class ToolExecutionSchema(BaseModel):
    """Record of a tool execution."""
    tool_name: str
    execution_time_ms: int
    status: str           # SUCCESS, FAILED, TIMED_OUT
    error_message: str | None = None
    timestamp: str


class RecommendationSchema(BaseModel):
    """A fraud investigation recommendation."""
    type: str
    priority: int = 0
    title: str
    impact: str


class InvestigationResponse(BaseModel):
    """Response for POST /investigations/run."""
    investigation_id: str
    transaction_id: str
    status: str
    severity: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    step_count: int
    max_steps: int = 20
    planner_decisions: list[PlannerDecisionSchema]
    tool_executions: list[ToolExecutionSchema]
    recommendations: list[RecommendationSchema]
    started_at: str
    completed_at: str | None = None
    total_duration_ms: int | None = None


class InvestigationDetailResponse(InvestigationResponse):
    """Response for GET /investigations/{id} with full state."""
    context: dict = {}
    evidence: list[dict] = []
    pattern_results: dict = {}
    similarity_results: dict = {}
    reasoning: dict = {}
    hypotheses: list[str] = []
    rule_draft: dict | None = None
```

**File:** `app/schemas/v1/common.py`

```python
from enum import StrEnum


class InvestigationStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ToolStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class RunMode(StrEnum):
    FULL = "FULL"
    QUICK = "QUICK"
```

**File:** `app/schemas/v1/recommendations.py`

Keep existing recommendation schemas for worklist endpoints:
- `RecommendationDetail`
- `RecommendationPayload`
- `AcknowledgeRequest`

Simplify by removing LLM-specific status fields (LLM status tracked at investigation level now).

---

## 5. Service Layer

### 5.1 InvestigationService (Simplified)

**File:** `app/services/investigation_service.py`

The service becomes a thin orchestrator around the LangGraph graph:

```python
import asyncio
import uuid

from app.agent.graph import build_investigation_graph
from app.agent.registry import ToolRegistry
from app.agent.state import create_initial_state
from app.core.config import get_settings
from app.persistence.investigation_repository import InvestigationRepository
from app.persistence.state_store import PostgresStateStore


class InvestigationService:
    """Thin service layer that invokes the LangGraph investigation graph."""

    def __init__(self, session, settings=None):
        self._session = session
        self._settings = settings or get_settings()
        self._investigation_repo = InvestigationRepository(session)
        self._state_store = PostgresStateStore(session)

    async def run_investigation(
        self,
        transaction_id: str,
        mode: str = "FULL",
    ) -> dict:
        """Run a complete fraud investigation."""
        investigation_id = str(uuid.uuid7())

        # 1. Create investigation record
        await self._investigation_repo.create(
            investigation_id=investigation_id,
            transaction_id=transaction_id,
            mode=mode,
            planner_model=self._settings.planner.model,
            max_steps=self._settings.langgraph.max_steps,
        )
        await self._session.commit()

        # 2. Build graph with tools and LLM
        graph = self._build_graph()

        # 3. Create initial state
        initial_state = create_initial_state(
            investigation_id=investigation_id,
            transaction_id=transaction_id,
            max_steps=self._settings.langgraph.max_steps,
        )

        # 4. Invoke with timeout
        try:
            async with asyncio.timeout(self._settings.langgraph.max_runtime_seconds):
                result = await graph.ainvoke(initial_state)
        except asyncio.TimeoutError:
            result = {**initial_state, "status": "TIMED_OUT", "error": "Investigation timed out"}

        return result

    async def get_investigation(self, investigation_id: str) -> dict:
        """Get full investigation detail."""
        investigation = await self._investigation_repo.get(investigation_id)
        if investigation is None:
            raise NotFoundError(f"Investigation {investigation_id} not found")

        state = await self._state_store.load_state(investigation_id)
        if state is None:
            return investigation

        # Merge investigation metadata with state
        return {**state, **investigation}

    async def resume_investigation(self, investigation_id: str) -> dict:
        """Resume a failed or interrupted investigation."""
        state = await self._state_store.load_state(investigation_id)
        if state is None:
            raise NotFoundError(f"No state found for investigation {investigation_id}")

        graph = self._build_graph()

        try:
            async with asyncio.timeout(self._settings.langgraph.max_runtime_seconds):
                result = await graph.ainvoke(state)
        except asyncio.TimeoutError:
            result = {**state, "status": "TIMED_OUT", "error": "Resume timed out"}

        return result

    def _build_graph(self):
        """Build the investigation graph with all dependencies."""
        llm = get_chat_model(self._settings)
        registry = build_tool_registry(
            session=self._session,
            settings=self._settings,
        )
        return build_investigation_graph(
            registry=registry,
            llm=llm,
            settings=self._settings,
        )
```

### 5.2 RecommendationService (Preserved)

Keep existing `RecommendationService`:
- `get_worklist(filters, pagination)` — query `ops_agent_recommendations` with keyset pagination
- `acknowledge(recommendation_id, analyst_id, action)` — update status, write audit
- No changes needed — recommendations are still stored the same way

### 5.3 Removed Services

| Service | Reason |
|---------|--------|
| `insight_service.py` | Insights are part of investigation response; no separate query needed |
| `rule_draft_service.py` | Rule drafts generated in investigation; export via recommendation flow |

---

## 6. API Route Implementations

### 6.1 Investigations Route

**File:** `app/api/routes/investigations.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import RequireOpsRun, RequireOpsRead
from app.core.database import get_session
from app.schemas.v1.investigations import (
    RunRequest,
    InvestigationResponse,
    InvestigationDetailResponse,
)
from app.services.investigation_service import InvestigationService

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("/run", response_model=InvestigationResponse)
async def run_investigation(
    request: RunRequest,
    _auth: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    """Start a new fraud investigation."""
    service = InvestigationService(session)
    result = await service.run_investigation(
        transaction_id=request.transaction_id,
        mode=request.mode,
    )
    return InvestigationResponse(**_map_state_to_response(result))


@router.get("/{investigation_id}", response_model=InvestigationDetailResponse)
async def get_investigation(
    investigation_id: str,
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get full investigation details."""
    service = InvestigationService(session)
    result = await service.get_investigation(investigation_id)
    return InvestigationDetailResponse(**result)


@router.post("/{investigation_id}/resume", response_model=InvestigationResponse)
async def resume_investigation(
    investigation_id: str,
    _auth: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    """Resume a failed or interrupted investigation."""
    service = InvestigationService(session)
    result = await service.resume_investigation(investigation_id)
    return InvestigationResponse(**_map_state_to_response(result))


def _map_state_to_response(state: dict) -> dict:
    """Map InvestigationState dict to response fields."""
    started = state.get("started_at", "")
    completed = state.get("completed_at")
    total_ms = None
    if started and completed:
        # Calculate duration
        from datetime import datetime, timezone
        t0 = datetime.fromisoformat(started)
        t1 = datetime.fromisoformat(completed)
        total_ms = int((t1 - t0).total_seconds() * 1000)

    return {
        "investigation_id": state["investigation_id"],
        "transaction_id": state["transaction_id"],
        "status": state.get("status", "UNKNOWN"),
        "severity": state.get("severity", "LOW"),
        "confidence_score": state.get("confidence_score", 0.0),
        "step_count": state.get("step_count", 0),
        "max_steps": state.get("max_steps", 20),
        "planner_decisions": state.get("planner_decisions", []),
        "tool_executions": state.get("tool_executions", []),
        "recommendations": state.get("recommendations", []),
        "started_at": started,
        "completed_at": completed,
        "total_duration_ms": total_ms,
    }
```

---

## 7. LangChain LLM Provider

**File:** `app/llm/provider.py` (rewritten)

Replaces the LiteLLM/Ollama dual-provider with LangChain's `BaseChatModel` ecosystem.

```python
from langchain_core.language_models import BaseChatModel
from app.core.config import Settings


def get_chat_model(settings: Settings) -> BaseChatModel:
    """
    Factory: create a LangChain ChatModel from settings.

    Supports:
    - anthropic/<model>  → ChatAnthropic
    - ollama/<model>     → ChatOllama
    - openai/<model>     → ChatOpenAI (future)
    """
    model_spec = settings.planner.model
    provider, _, model_name = model_spec.partition("/")

    if not model_name:
        # No prefix — default to Anthropic
        model_name = model_spec
        provider = "anthropic"

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model_name,
            base_url=settings.llm.base_url or "http://localhost:11434",
            temperature=settings.planner.temperature,
            num_predict=settings.planner.max_tokens,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            api_key=settings.llm.api_key,
            temperature=settings.planner.temperature,
            max_tokens=settings.planner.max_tokens,
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Use 'anthropic/<model>' or 'ollama/<model>'."
        )
```

### 7.1 Dependency Changes in `pyproject.toml`

**Add:**

```toml
dependencies = [
    # ... existing ...
    "langgraph>=0.3.0",
    "langchain-core>=0.3.0",
    "langchain-anthropic>=0.3.0",
    "langchain-ollama>=0.3.0",
]
```

**Remove:**

```toml
# Remove this line:
"litellm>=1.78.0,<2.0",
```

### 7.2 PII Redaction

Move `app/llm/redaction.py` to `app/utils/redaction.py`. Logic unchanged — it applies allowlist/blocklist filtering before any LLM call. Used by `ReasoningTool`.

---

## 8. Application Entry Point

**File:** `app/main.py` — Updates

### 8.1 Router Changes

```python
# BEFORE (6 routers):
app.include_router(monitoring_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1/ops-agent")
app.include_router(insights_router, prefix="/api/v1/ops-agent")
app.include_router(recommendations_router, prefix="/api/v1/ops-agent")
app.include_router(rule_drafts_router, prefix="/api/v1/ops-agent")

# AFTER (4 routers):
app.include_router(monitoring_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1/ops-agent")
app.include_router(recommendations_router, prefix="/api/v1/ops-agent")
```

### 8.2 Lifespan Changes

Add TM client initialization:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Database
    engine = create_async_engine(settings.database)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory

    # TM Client (NEW)
    tm_client = TMClient(settings.tm_client)
    app.state.tm_client = tm_client

    yield

    await close_async_http_client()
    await reset_engine()
```

### 8.3 Middleware — Unchanged

All 3 middlewares preserved:
- `security_headers_middleware`
- `payload_size_guard`
- `request_id_middleware`

---

## 9. OpenAPI Spec Update

After implementation, regenerate OpenAPI spec:

```bash
uv run openapi-export
```

Key changes in spec:
- New `/investigations/run` response schema
- New `/investigations/{id}` response schema
- New `/investigations/{id}/resume` endpoint
- Removed `/transactions/{txn_id}/insights` endpoint
- Removed `/rule-drafts` endpoints
