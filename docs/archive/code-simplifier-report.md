# Code Quality Analysis Report: Card Fraud Ops Analyst Agent

**Generated:** 2026-02-18
**Agent:** Code Simplifier
**Analysis Scope:** Full codebase review for simplification opportunities

---

## Executive Summary

This codebase demonstrates **strong architectural patterns** and **high code quality overall**. The project follows a clean separation of concerns with a core/adapter split pattern, comprehensive type hints, and well-structured async patterns. However, there are several opportunities for simplification and consistency improvements that would enhance maintainability.

**Key Strengths:**
- Clean core/adapter architecture (`*_core.py` for pure logic, `*.py` for DB-bound adapters)
- Comprehensive type annotations using modern Python 3.14 syntax
- Consistent use of Pydantic for validation
- Strong security practices (PII redaction, JWT validation, input validation)
- Good use of async/await patterns throughout

**Areas for Improvement:**
1. Code duplication in attribute access patterns
2. Inconsistent data type handling (dict vs object attributes)
3. Some long functions that could benefit from extraction
4. Repetitive LLM payload construction patterns
5. Inconsistent naming conventions in places

---

## Detailed Findings

### 1. Repetitive Attribute Access Pattern (HIGH PRIORITY)

**Location:** Multiple files throughout the codebase

**Issue:** There's widespread repetition of code to handle both dict-based and object-based attribute access:

```python
# Pattern seen repeatedly across the codebase
if hasattr(transaction, "amount"):
    amount = float(transaction.amount)
elif isinstance(transaction, dict):
    amount = float(transaction.get("amount", 0))
else:
    amount = 0.0
```

**Files affected:**
- `app/agents/pattern_engine_core.py` (lines 90-95, 246-249, 379-384, 395-398, 623-626)
- `app/agents/similarity_engine.py` (lines 184-199, 319-324, 368-373)
- `app/agents/recommendation_engine.py` (lines 408-433)
- `app/persistence/context_reader.py` (implicit handling)

**Recommendation:** Create a utility function for safe attribute extraction:

```python
# app/utils/attr_access.py
from typing import Any

def get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Safely get attribute from dict or object.

    Supports fallback keys for common field name variations.
    """
    if obj is None:
        return default

    for key in keys:
        if isinstance(obj, dict):
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)

        if value is not None:
            return value

    return default

# Usage:
amount = get_attr(transaction, "amount", "transaction_amount", default=0.0)
```

**Impact:** Reduces ~50-100 lines of duplicated code across the codebase.

---

### 2. Long Functions in `recommendation_engine.py` (MEDIUM PRIORITY)

**Location:** `app/agents/recommendation_engine.py`

**Issue:** The `_generate_summary` method (lines 250-398) is 149 lines long and handles multiple concerns:
- Pattern detail extraction
- Indicator string generation
- Similarity score processing
- Transaction context building
- Card history context building
- Data quality flag generation

**Recommendation:** Extract into smaller, focused methods:

```python
def _generate_summary(self, ...) -> str:
    """Generate detailed deterministic insight summary from scored evidence."""
    details = self._pattern_details(pattern_scores)
    indicators = self._build_indicators(details, similarity_result)
    severity_line = self._build_severity_line(severity, indicators)
    tx_line = self._build_transaction_context_line(context)
    card_line = self._build_card_history_line(context)
    gaps = self._build_data_quality_flags(context)

    parts = [severity_line, tx_line, card_line]
    if gaps:
        parts.append(f"Data gaps: {', '.join(gaps)}.")

    return " ".join(parts)

def _build_indicators(self, details: dict, similarity_result: Any) -> list[str]:
    """Extract and format fraud indicators."""
    # ... existing indicator building logic ...
```

**Impact:** Improves testability and readability.

---

### 3. LLM Payload Construction Duplication (MEDIUM PRIORITY)

**Location:** `app/agents/recommendation_engine.py` (lines 143-185)

**Issue:** The `_llm_payload_fields` method has duplicated structure for three different cases (no reasoning, error, success) with mostly the same keys being set.

**Recommendation:** Simplify using a builder pattern:

```python
@staticmethod
def _llm_payload_fields(reasoning: dict[str, Any] | None, model_mode: str) -> dict[str, Any]:
    """Normalize LLM metadata to make fallback/audit state explicit."""
    payload = {
        "llm_status": "not_requested",
        "model_mode": model_mode,
        "llm_narrative": "",
        "llm_confidence": None,
        "llm_risk_assessment": None,
        "llm_error": None,
        "llm_model": None,
        "llm_latency_ms": None,
        "llm_reasoning_hash": None,
    }

    if reasoning is None:
        return payload

    error = reasoning.get("error")
    if error:
        payload["llm_status"] = "fallback"
        payload["llm_error"] = str(reasoning.get("error_detail") or error)
        return payload

    payload["llm_status"] = "applied" if model_mode == "hybrid" else "deterministic"
    payload["llm_narrative"] = reasoning.get("narrative", "")
    payload["llm_confidence"] = reasoning.get("confidence")
    payload["llm_risk_assessment"] = reasoning.get("risk_assessment")
    payload["llm_model"] = reasoning.get("llm_model")
    payload["llm_latency_ms"] = reasoning.get("llm_latency_ms")
    payload["llm_reasoning_hash"] = RecommendationEngine._reasoning_hash(reasoning)

    return payload
```

**Impact:** Reduces ~40 lines to ~30 lines with clearer flow.

---

### 4. Inconsistent Similarity Score Access (LOW PRIORITY)

**Location:** Multiple files

**Issue:** Similarity scores are accessed inconsistently - sometimes as `similarity_result.overall_score` (object attribute) and sometimes as `similarity_analysis["overall_score"]` (dict access). This creates complexity throughout the pipeline.

**Files affected:**
- `app/agents/pipeline.py` (lines 431-437)
- `app/agents/recommendation_engine.py` (lines 491-506)
- `app/agents/similarity_engine.py` (lines 52, 114)

**Recommendation:** Create a consistent accessor utility:

```python
# app/agents/similarity_utils.py
from typing import Any

def get_similarity_score(data: Any) -> float:
    """Extract overall similarity score from various formats."""
    if data is None:
        return 0.0
    if isinstance(data, dict):
        return float(data.get("overall_score", 0.0))
    return float(getattr(data, "overall_score", 0.0))
```

**Impact:** Reduces confusion and potential for bugs.

---

### 5. Action Plan Generation Duplication (LOW PRIORITY)

**Location:**
- `app/agents/pipeline.py` (lines 686-828)
- `app/services/investigation_service.py` (lines 287-354)

**Issue:** Both `_build_action_plan` methods have similar logic for generating action plans with slightly different implementations. The service and pipeline both duplicate this concern.

**Recommendation:** Extract to a shared module:

```python
# app/agents/action_planner.py
from typing import Any

class ActionPlanner:
    """Generate next-best actions for fraud analysts."""

    def generate(
        self,
        recommendations: list[dict[str, Any]],
        severity: str,
        evidence: list[dict[str, Any]] | None = None,
        llm_status: str = "",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        # ... unified action plan generation logic ...
```

**Impact:** Eliminates ~140 lines of duplication.

---

### 6. Counter-Evidence Flag Extraction Duplication (LOW PRIORITY)

**Location:**
- `app/agents/similarity_engine.py` (lines 135-181)
- `app/agents/recommendation_engine.py` (lines 202-228)

**Issue:** Both files have similar logic for extracting counter-evidence flags from transaction context, checking alternate field names.

**Recommendation:** Move to a shared utility:

```python
# app/agents/counter_evidence.py
from typing import Any

def extract_counter_evidence_flags(transaction_context: dict[str, Any] | None) -> dict[str, bool]:
    """Extract normalized counter-evidence booleans from TM context JSON."""
    if not isinstance(transaction_context, dict):
        return {}

    def get_first(*keys: str, default: Any = None) -> Any:
        for key in keys:
            value = transaction_context.get(key)
            if value is not None:
                return value
        return default

    three_ds = get_first("three_ds_authenticated", "3ds_verified")
    trusted_device = get_first("is_trusted_device", "device_trusted")
    # ... etc ...

    return {
        "three_ds_authenticated": bool(three_ds) if three_ds is not None else False,
        # ... etc ...
    }
```

**Impact:** Reduces duplication and provides single source of truth.

---

### 7. Stage Status Calculation Repetition (LOW PRIORITY)

**Location:** `app/agents/pipeline.py` (lines 612-626)

**Issue:** The stage status calculation logic is somewhat convoluted with nested conditions.

**Recommendation:** Extract to a clearer method:

```python
def _get_stage_status(self, stage_name: str, stage_durations: dict[str, float]) -> str:
    """Get the status of a pipeline stage."""
    return "success" if stage_name in stage_durations else "skipped"

def _get_llm_stage_status(self, llm_status: str, stage_durations: dict[str, float]) -> str:
    """Get the LLM stage status with fallback handling."""
    if not self._settings.features.enable_llm_reasoning:
        return "disabled"
    if llm_status in {"fallback", "failed"}:
        return "fallback"
    return self._get_stage_status("llm_reasoning", stage_durations)
```

**Impact:** Improved readability.

---

### 8. Hash Calculation Duplication (VERY LOW PRIORITY)

**Location:**
- `app/agents/pipeline.py` (lines 831-841)
- `app/agents/recommendation_engine.py` (lines 188-200)

**Issue:** Nearly identical `_reasoning_hash` methods in two different modules.

**Recommendation:** Move to a shared utility:

```python
# app/utils/hashing.py
import hashlib
import json

def hash_llm_reasoning(reasoning: dict[str, Any]) -> str | None:
    """Create stable hash for LLM reasoning payload for audit correlation."""
    narrative = str(reasoning.get("narrative", "")).strip()
    if not narrative:
        return None

    basis = {
        "model_mode": reasoning.get("model_mode"),
        "narrative": narrative,
        "risk_assessment": reasoning.get("risk_assessment"),
        "confidence": reasoning.get("confidence"),
    }
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True).encode("utf-8")
    ).hexdigest()
```

**Impact:** -15 LOC, single source of truth.

---

### 9. Configuration Complexity (MEDIUM PRIORITY)

**Location:** `app/core/config.py`

**Issue:** The `Settings` class has become quite large with many nested configurations. The model validator `fill_ollama_api_key` is duplicated between `LLMConfig` and `VectorSearchConfig` (lines 326-332, 348-365).

**Recommendation:** Extract the common API key fallback logic:

```python
def _fill_ollama_api_key_if_needed(
    api_key: SecretStr,
    is_ollama_provider: bool
) -> SecretStr:
    """Fallback to OLLAMA_API_KEY env var for Ollama providers."""
    if api_key.get_secret_value() or not is_ollama_provider:
        return api_key

    ollama_key = os.getenv("OLLAMA_API_KEY", "")
    if ollama_key:
        return SecretStr(ollama_key)
    return api_key
```

**Impact:** -30 LOC, improved maintainability.

---

### 10. SQL Query String Duplication (LOW PRIORITY)

**Location:** `app/persistence/context_reader.py`

**Issue:** The raw SQL queries are embedded as strings, making them harder to maintain and test. While this is intentional for performance (avoiding ORM overhead), consider extracting query templates.

**Recommendation:** For better maintainability, consider:

```python
# app/persistence/queries.py
GET_TRANSACTION_BY_ID = """
    SELECT id, transaction_id,
           transaction_amount AS amount,
           transaction_currency AS currency,
           ...
    FROM fraud_gov.transactions
    WHERE transaction_id = :transaction_id
"""

# Then in context_reader.py:
from app.persistence.queries import GET_TRANSACTION_BY_ID

async def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
    query = text(GET_TRANSACTION_BY_ID)
    ...
```

**Impact:** Improved maintainability and testability.

---

## Summary of Recommendations by Priority

| Priority | Issue | Files Affected | Estimated Impact |
|----------|-------|----------------|------------------|
| HIGH | Attribute access pattern duplication | 10+ files | -100 LOC, improved reliability |
| MEDIUM | Long `_generate_summary` function | recommendation_engine.py | Better testability |
| MEDIUM | LLM payload construction | recommendation_engine.py | -40 LOC |
| MEDIUM | Config API key fallback duplication | config.py | -30 LOC |
| LOW | Similarity score access inconsistency | 5 files | Reduced bugs |
| LOW | Action plan generation duplication | pipeline.py, investigation_service.py | -140 LOC |
| LOW | Counter-evidence flag extraction duplication | similarity_engine.py, recommendation_engine.py | -50 LOC |
| LOW | Stage status calculation | pipeline.py | Improved readability |
| VERY LOW | Hash calculation duplication | pipeline.py, recommendation_engine.py | -15 LOC |
| LOW | SQL query strings | context_reader.py | Improved maintainability |

**Total Potential Code Reduction:** ~375 lines of duplicated/complex code

---

## Positive Patterns to Preserve

The following patterns in the codebase are excellent and should be maintained:

1. **Core/Adapter Split**: The `*_core.py` files containing pure functions separate from DB access is a strong pattern.

2. **Frozen Dataclasses**: Used appropriately in `conflict_matrix.py` and `evidence_builder.py` for immutable data.

3. **Type Aliases**: `Annotated[AuthenticatedUser, Depends(...)]` pattern in dependencies.py is clean and reusable.

4. **Structured Error Handling**: The error hierarchy in `errors.py` with proper HTTP status codes is well-designed.

5. **Security-First Design**: PII redaction, JWT validation, and input validation are consistently applied.

6. **Observability Integration**: OpenTelemetry tracing is well-integrated throughout the pipeline.

---

## Testing Considerations

Many of the recommended simplifications would improve testability:

1. Extracting attribute access to a utility makes it easier to mock in tests
2. Breaking down long functions allows for more targeted unit tests
3. Shared utilities reduce the need for duplicate test setups

The codebase already has strong test coverage (278 tests reported), which is excellent for refactoring.

---

## Implementation Roadmap

### Phase 1: High-Priority Items (1-2 days)
1. Create `app/utils/attr_access.py` with `get_attr()` utility
2. Replace duplicated attribute access patterns across 10+ files
3. Add comprehensive tests for the utility
4. Run full test suite to ensure no regressions

### Phase 2: Medium-Priority Items (2-3 days)
1. Refactor `_generate_summary()` in `recommendation_engine.py`
2. Simplify `_llm_payload_fields()` method
3. Extract Ollama API key fallback logic in `config.py`
4. Add tests for new helper methods

### Phase 3: Low-Priority Items (3-4 days)
1. Create similarity score accessor utility
2. Extract action planner to shared module
3. Consolidate counter-evidence flag extraction
4. Refactor stage status calculation
5. Move hash calculation to utility module

### Phase 4: Final Polish (1 day)
1. Extract SQL queries to separate module
2. Update documentation
3. Final code review
4. Update memory files with new patterns

**Total Estimated Effort:** 7-10 developer days

---

## Conclusion

This codebase demonstrates **high-quality software engineering practices**. The recommended improvements are primarily around:
- **Reducing duplication** in cross-cutting concerns
- **Extracting overly long functions** for better testability
- **Standardizing common patterns** (attribute access, score extraction)

The architectural foundation is solid, and these improvements would enhance maintainability without requiring significant refactoring of the core design.

---

## References

- **Agent ID:** afa8026 (can be resumed for follow-up work)
- **Analysis Duration:** ~170 seconds
- **Files Analyzed:** 150+ files across the codebase
- **Tools Used:** Read, Grep, Glob (26 tool calls)
