# TDD-004: Persistence & State Management

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** ADR-002, ADR-007, TDD-001, TDD-002

---

## 1. Overview

Evolve the database schema to support agentic investigations. Add 2 new tables (`ops_agent_investigation_state`, `ops_agent_tool_execution_log`), evolve `ops_agent_runs` → `ops_agent_investigations`, keep existing insight/recommendation/audit tables with simplified schemas. Implement `PostgresStateStore` for JSONB state persistence with versioning.

---

## 2. Schema Evolution Strategy

### 2.1 Key Decision: Unify `ops_agent_runs` → `ops_agent_investigations`

The existing `ops_agent_runs` table and ADR-002's proposed `investigations` table serve the same purpose — tracking investigation lifecycle. Instead of creating a separate table, we **ALTER** the existing table:

- Rename to `ops_agent_investigations` (semantic clarity for agentic model)
- Add agentic columns: `priority`, `step_count`, `max_steps`, `planner_model`, `final_confidence`
- Keep existing columns: `id`, `mode`, `status`, `transaction_id`, `severity`, `started_at`, `completed_at`, etc.

### 2.2 Embedding Dimension Decision

Keep **1024** dimensions (matches `mxbai-embed-large` model currently deployed). ADR-007 suggests 1536 but that assumes OpenAI `text-embedding-3-large`. We use `mxbai-embed-large` which outputs 1024. If the embedding model changes, a separate migration handles the dimension change.

---

## 3. New Migration: `010_agentic_schema.sql`

```sql
-- ============================================================
-- Migration 010: Agentic Architecture Schema Evolution
-- ============================================================

-- ── 1. Rename ops_agent_runs → ops_agent_investigations ───────
ALTER TABLE IF EXISTS fraud_gov.ops_agent_runs
    RENAME TO ops_agent_investigations;

-- Rename associated indexes
ALTER INDEX IF EXISTS fraud_gov.idx_ops_agent_runs_status
    RENAME TO idx_ops_agent_investigations_status;
ALTER INDEX IF EXISTS fraud_gov.idx_ops_agent_runs_transaction_id
    RENAME TO idx_ops_agent_investigations_transaction_id;
ALTER INDEX IF EXISTS fraud_gov.idx_ops_agent_runs_started_at
    RENAME TO idx_ops_agent_investigations_started_at;

-- ── 2. Add agentic columns to investigations ─────────────────
ALTER TABLE fraud_gov.ops_agent_investigations
    ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'MEDIUM',
    ADD COLUMN IF NOT EXISTS step_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_steps INTEGER DEFAULT 20,
    ADD COLUMN IF NOT EXISTS planner_model TEXT,
    ADD COLUMN IF NOT EXISTS final_confidence FLOAT;

-- ── 3. Investigation State Store (JSONB) ──────────────────────
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_investigation_state (
    investigation_id UUID PRIMARY KEY
        REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE,
    state JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE fraud_gov.ops_agent_investigation_state IS
    'JSONB state store for LangGraph investigation state. Versioned for resume/replay.';

-- ── 4. Tool Execution Log ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_tool_execution_log (
    id UUID PRIMARY KEY,
    investigation_id UUID NOT NULL
        REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    input_summary JSONB,
    output_summary JSONB,
    execution_time_ms INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'SUCCESS',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_execution_log_investigation
    ON fraud_gov.ops_agent_tool_execution_log(investigation_id);

CREATE INDEX IF NOT EXISTS idx_tool_execution_log_tool_name
    ON fraud_gov.ops_agent_tool_execution_log(tool_name);

CREATE INDEX IF NOT EXISTS idx_tool_execution_log_created_at
    ON fraud_gov.ops_agent_tool_execution_log(created_at DESC);

COMMENT ON TABLE fraud_gov.ops_agent_tool_execution_log IS
    'Audit log of every tool execution within an investigation. Supports replay and debugging.';

-- ── 5. Grants ─────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON fraud_gov.ops_agent_investigation_state
    TO fraud_gov_app_user;

GRANT SELECT, INSERT ON fraud_gov.ops_agent_tool_execution_log
    TO fraud_gov_app_user;
```

---

## 4. Complete Table Inventory (Post-Migration)

| Table | Disposition | Owner |
|-------|------------|-------|
| `ops_agent_investigations` | **RENAMED** from `ops_agent_runs` + new columns | This project |
| `ops_agent_investigation_state` | **NEW** — JSONB state store | This project |
| `ops_agent_tool_execution_log` | **NEW** — tool execution audit | This project |
| `ops_agent_transaction_embeddings` | **PRESERVED** — pgvector 1024-dim | This project |
| `ops_agent_insights` | **PRESERVED** | This project |
| `ops_agent_evidence` | **PRESERVED** | This project |
| `ops_agent_recommendations` | **PRESERVED** | This project |
| `ops_agent_rule_drafts` | **PRESERVED** | This project |
| `ops_agent_audit_log` | **PRESERVED** | This project |

---

## 5. PostgresStateStore

**File:** `app/persistence/state_store.py`

### 5.1 Interface

```python
class PostgresStateStore:
    """JSONB state persistence with optimistic versioning."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_state(
        self,
        investigation_id: str,
        state: dict,
    ) -> int:
        """
        Upsert investigation state. Returns new version number.

        Uses ON CONFLICT DO UPDATE to increment version atomically.
        """
        query = text("""
            INSERT INTO fraud_gov.ops_agent_investigation_state
                (investigation_id, state, version, created_at, updated_at)
            VALUES
                (:id, :state::jsonb, 1, NOW(), NOW())
            ON CONFLICT (investigation_id) DO UPDATE SET
                state = :state::jsonb,
                version = ops_agent_investigation_state.version + 1,
                updated_at = NOW()
            RETURNING version
        """)
        result = await self._session.execute(query, {
            "id": investigation_id,
            "state": json.dumps(state),
        })
        row = result.fetchone()
        return row[0]

    async def load_state(
        self,
        investigation_id: str,
    ) -> dict | None:
        """
        Load latest state for investigation.

        Returns None if no state exists (investigation not started or purged).
        """
        query = text("""
            SELECT state, version
            FROM fraud_gov.ops_agent_investigation_state
            WHERE investigation_id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        row = result.fetchone()
        if row is None:
            return None
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]

    async def get_version(self, investigation_id: str) -> int:
        """Get current state version. Returns 0 if no state exists."""
        query = text("""
            SELECT version
            FROM fraud_gov.ops_agent_investigation_state
            WHERE investigation_id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        row = result.fetchone()
        return row[0] if row else 0

    async def delete_state(self, investigation_id: str) -> bool:
        """Delete state (for cleanup/retention). Returns True if deleted."""
        query = text("""
            DELETE FROM fraud_gov.ops_agent_investigation_state
            WHERE investigation_id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        return result.rowcount > 0
```

### 5.2 State Persistence Timing

State is persisted at these points:

| When | Why |
|------|-----|
| After every tool execution (in `tool_executor_node`) | Resume from any step on failure |
| At completion (in `completion_node`) | Final state snapshot |
| On timeout/error | Capture state at failure point |

### 5.3 State Size Considerations

Typical `InvestigationState` JSONB size:
- Empty: ~500 bytes
- After context: ~10 KB
- After all tools: ~50 KB
- Maximum (worst case): ~200 KB

PostgreSQL JSONB handles this efficiently. No compression needed.

---

## 6. Investigation Repository

**File:** `app/persistence/investigation_repository.py`

Replaces `run_repository.py`. Same patterns (raw SQL, `text()`, `uuid.uuid7()`, `row_to_dict()`).

### 6.1 Interface

```python
class InvestigationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        investigation_id: str,
        transaction_id: str,
        mode: str,
        priority: str = "MEDIUM",
        max_steps: int = 20,
        planner_model: str | None = None,
    ) -> dict:
        """Create a new investigation record."""

    async def get(self, investigation_id: str) -> dict | None:
        """Get investigation by ID."""

    async def complete(
        self,
        investigation_id: str,
        status: str,
        severity: str,
        final_confidence: float,
        step_count: int,
        stage_durations: dict | None = None,
    ) -> dict:
        """Mark investigation as completed."""

    async def list_recent(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> list[dict]:
        """List recent investigations with keyset pagination."""
```

---

## 7. Tool Execution Log Repository

**File:** `app/persistence/tool_log_repository.py`

### 7.1 Interface

```python
class ToolLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_execution(
        self,
        investigation_id: str,
        tool_name: str,
        step_number: int,
        input_summary: dict,
        output_summary: dict,
        execution_time_ms: int,
        status: str = "SUCCESS",
        error_message: str | None = None,
    ) -> dict:
        """Log a single tool execution."""
        execution_id = str(uuid.uuid7())
        query = text("""
            INSERT INTO fraud_gov.ops_agent_tool_execution_log
                (id, investigation_id, tool_name, step_number,
                 input_summary, output_summary, execution_time_ms,
                 status, error_message, created_at)
            VALUES
                (:id, :inv_id, :tool, :step, :input::jsonb,
                 :output::jsonb, :time_ms, :status, :error, NOW())
            RETURNING *
        """)
        result = await self._session.execute(query, {
            "id": execution_id,
            "inv_id": investigation_id,
            "tool": tool_name,
            "step": step_number,
            "input": json.dumps(input_summary),
            "output": json.dumps(output_summary),
            "time_ms": execution_time_ms,
            "status": status,
            "error": error_message,
        })
        return row_to_dict(result.fetchone())

    async def get_executions(
        self,
        investigation_id: str,
    ) -> list[dict]:
        """Get all tool executions for an investigation, ordered by step."""
        query = text("""
            SELECT *
            FROM fraud_gov.ops_agent_tool_execution_log
            WHERE investigation_id = :id
            ORDER BY step_number ASC
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        return [row_to_dict(r) for r in result.fetchall()]

    async def log_executions_batch(
        self,
        investigation_id: str,
        executions: list[dict],
    ) -> int:
        """Batch insert tool execution logs. Returns count inserted."""
        # Used by completion node to persist all tool logs at once
```

---

## 8. Existing Repositories — Changes

| Repository | Change |
|-----------|--------|
| `insight_repository.py` | **KEEP** — simplify evidence handling. Tools provide structured evidence in `InvestigationState`, completion node calls `upsert_insight()` |
| `recommendation_repository.py` | **KEEP** — called by completion node to persist recommendations |
| `rule_draft_repository.py` | **KEEP** — called by completion node to persist rule drafts |
| `audit_repository.py` | **KEEP** — called by completion node to append audit entries |
| `base.py` | **KEEP** — `row_to_dict()` and `BaseCursor` unchanged |
| `context_reader.py` | **DELETE** — replaced by TM API client (`app/clients/tm_client.py`) |
| `run_repository.py` | **DELETE** — replaced by `investigation_repository.py` |

---

## 9. Memory Model (ADR-007)

Three-layer memory architecture:

### 9.1 Short-Term Memory (Working Memory)

- `InvestigationState` TypedDict
- Lives in process memory during graph execution
- Persisted to `ops_agent_investigation_state` after every tool step
- Lifetime: single investigation

### 9.2 Long-Term Memory (Investigation History)

- `ops_agent_investigations` table
- `ops_agent_insights` + `ops_agent_evidence` tables
- `ops_agent_recommendations` table
- `ops_agent_audit_log` table
- Lifetime: configurable retention (default 10 years per ADR-007)

### 9.3 Vector Memory (Semantic Knowledge)

- `ops_agent_transaction_embeddings` table (pgvector, 1024 dimensions)
- Written after investigation completes (completion node)
- Read by `SimilarityTool` during investigations
- Enables learning from past investigations

### 9.4 Memory Write Flow (Completion Node)

```
Investigation completes
    ├── Save final state → ops_agent_investigation_state
    ├── Insert/update investigation → ops_agent_investigations
    ├── Insert insights + evidence → ops_agent_insights, ops_agent_evidence
    ├── Insert recommendations → ops_agent_recommendations
    ├── Insert tool logs → ops_agent_tool_execution_log
    ├── Insert audit entry → ops_agent_audit_log
    └── Generate + store embedding → ops_agent_transaction_embeddings
```

### 9.5 Memory Read Flow (During Investigation)

```
Investigation starts
    ├── ContextTool → TM API (not DB)
    ├── SimilarityTool → ops_agent_transaction_embeddings (pgvector query)
    └── All other tools → pure computation on state
```

---

## 10. Safe Reset Commands (Updated)

```bash
# Drop and recreate ONLY this project's tables (updated table names)
doppler run --config local -- uv run python -m scripts.db_reset_tables

# Tables to drop (in order due to FK constraints):
# 1. ops_agent_tool_execution_log
# 2. ops_agent_investigation_state
# 3. ops_agent_evidence
# 4. ops_agent_insights
# 5. ops_agent_recommendations
# 6. ops_agent_rule_drafts
# 7. ops_agent_audit_log
# 8. ops_agent_transaction_embeddings
# 9. ops_agent_investigations

# Clear data (keep schema):
doppler run --config local -- uv run python -m scripts.db_reset_data
```

### NEVER DO THIS

```sql
DROP SCHEMA fraud_gov CASCADE;  -- DESTROYS ALL PROJECTS' DATA
```

---

## 11. Data Flow Diagram

```
┌──────────────────────┐
│   API Request        │
│   (transaction_id)   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  InvestigationService │
│  (create record)     │──────► ops_agent_investigations (INSERT)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  LangGraph.ainvoke() │
│                      │
│  ┌────────────────┐  │
│  │ Planner Node   │  │
│  └───────┬────────┘  │
│          │           │
│  ┌───────▼────────┐  │
│  │ Tool Executor  │──┼──► state_store.save_state() (after each tool)
│  └───────┬────────┘  │
│          │           │
│  ┌───────▼────────┐  │
│  │ Completion     │──┼──► ops_agent_investigation_state (final)
│  │                │──┼──► ops_agent_tool_execution_log (batch)
│  │                │──┼──► ops_agent_insights + evidence
│  │                │──┼──► ops_agent_recommendations
│  │                │──┼──► ops_agent_audit_log
│  │                │──┼──► ops_agent_transaction_embeddings
│  │                │──┼──► ops_agent_investigations (UPDATE: complete)
│  └────────────────┘  │
└──────────────────────┘
```
