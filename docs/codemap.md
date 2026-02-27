# Code Map

Current implementation map for the LangGraph-based agentic fraud ops analyst service.

## Top-Level Layout

- `app/` - FastAPI app, graph runtime, tools, persistence, schemas
- `cli/` - `uv run` command entry points
- `scripts/` - local utilities (E2E runner, seed scripts, reporting helpers)
- `db/migrations/` - SQL migrations for `ops_agent_*` tables
- `docs/` - canonical project documentation
- `tests/` - unit, integration, smoke, E2E tests

## Application Modules

### `app/agent/`

- `graph.py` - LangGraph graph assembly and node wiring
- `planner.py` - next-step selection logic
- `executor.py` - tool execution + per-stage summaries
- `completion.py` - final response assembly
- `state.py` - investigation state schema + update helpers
- `registry.py` - tool registry

### `app/tools/`

- `context_tool.py` - transaction + history context loading
- `pattern_tool.py` - fraud pattern scoring
- `similarity_tool.py` - embedding + vector candidate retrieval
- `reasoning_tool.py` - LLM-based reasoning synthesis
- `recommendation_tool.py` - analyst action recommendations
- `rule_draft_tool.py` - draft rule package generation
- `_core/` - pure logic modules shared by tools

### `app/services/`

- `investigation_service.py` - run/resume/get/list investigations, trace assembly
- `recommendation_service.py` - worklist and acknowledgement operations

### `app/persistence/`

- `investigation_repository.py`
- `state_store.py`
- `tool_log_repository.py`
- `insight_repository.py`
- `recommendation_repository.py`
- `rule_draft_repository.py`
- `audit_repository.py`

### `app/api/routes/`

- `investigations.py`
- `insights.py`
- `recommendations.py`
- `health.py`
- `monitoring.py`

## Request Flow

1. `POST /api/v1/ops-agent/investigations/run`
2. `InvestigationService.run_investigation()`
3. `agent/graph.py` executes planner/tool loop
4. Tool outputs persist into `ops_agent_*` tables
5. Response includes investigation summary + agent trace metadata

## Canonical Docs

- `docs/README.md` - docs index
- `docs/02-development/developer-guide.md` - developer workflow
- `docs/02-development/architecture.md` - architecture details
- `docs/03-api/ops-agent-api-contract-v1.md` - API contract
- `docs/06-operations/runbooks.md` - runtime operations
- `docs/07-reference/` - long-lived architecture and governance references
