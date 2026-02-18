# Card Fraud Ops Analyst Agent - Phase 2 Implementation Outline

## Planning Status

**This is a lightweight outline, not a detailed implementation plan.**

Detailed step-by-step planning (file-level changes, ordered steps, verification criteria) will happen after Phase 1 is implemented. Reasons:

1. **Phase 2 builds directly on Phase 1 stubs** — `rule_draft_engine.py` (currently `raise NotImplementedError`) and recommendation status transitions need to exist in code before we can plan exact changes.
2. **Exact file modifications depend on Phase 1's final shape** — repository interfaces, schema field names, and pipeline structure may evolve during Phase 1 implementation.
3. **Cross-repo coordination surfaces become concrete after Phase 1** — Rule Management's draft import endpoint and Portal's UI panels depend on the actual API contract shapes shipped in Phase 1.

---

## Objectives

- Enable the analyst action loop on recommendations (acknowledge, reject).
- Implement rule draft package generation from accepted recommendations.
- Implement export to Rule Management's maker-checker flow.
- Ensure action/audit trail immutability.

## Release Gates

- **Gate 2**: Scope-based authz, prompt guard/redaction, audit immutability checks pass.
- **Gate 3**: Portal integration, analyst acknowledge/reject, draft package creation, human final review enforced.

---

## Scope by Repository

### `card-fraud-ops-analyst-agent`

| Area | What Changes |
|------|-------------|
| `rule_draft_engine.py` | Replace `NotImplementedError` stub with full draft package generation logic |
| `recommendation_engine.py` | Add status transition enforcement (OPEN -> ACKNOWLEDGED/REJECTED -> EXPORTED) |
| `rule_draft_repository.py` | Full CRUD + export status tracking |
| `audit_engine.py` | Emit audit events for every status transition and export action |
| `services/rule_draft_service.py` | Replace Phase 1 stubs with generation, validation, and export orchestration |
| `services/recommendation_service.py` | Expand acknowledge/reject with downstream triggers (draft creation on accept) |
| `api/routes/rule_drafts.py` | Wire `POST /rule-drafts` and `POST /rule-drafts/{id}/export` to real logic |
| Schemas | Finalize `RuleDraftPayload` structure — normalized rule conditions, thresholds, metadata |

### `card-fraud-rule-management`

| Area | What Changes |
|------|-------------|
| New import endpoint | `POST /api/v1/ops-agent-drafts/import` — accepts draft package |
| Provenance fields | Persist `recommendation_id`, `insight_id`, `source=ops-agent` on draft entity |
| Maker-checker routing | Ingested draft enters existing approval workflow, no bypass |

### `card-fraud-intelligence-portal`

| Area | What Changes |
|------|-------------|
| Recommendation actions | UI buttons for acknowledge, reject on recommendation cards |
| Rule draft creation | "Create Rule Draft" action from accepted recommendation |
| Draft export | "Export to Rule Management" action with status feedback |
| Evidence timeline | Provenance and action history panel per recommendation |

### `card-fraud-transaction-management`

| Area | What Changes |
|------|-------------|
| Transaction overview | Optional: include latest Ops Agent insight summary in existing response |

---

## Key New Files (Estimated)

```
app/agents/rule_draft_engine.py          # Full implementation (replaces stub)
app/agents/rule_draft_core.py            # PURE: draft package assembly, validation
app/schemas/v1/rule_draft_payload.py     # Normalized rule draft package schema
```

## Key Design Questions (To Resolve During Detailed Planning)

1. **Draft package schema** — What normalized structure for rule conditions/thresholds does Rule Management expect?
2. **Export transport** — Direct HTTP call to RM, or async via event/queue?
3. **Partial export handling** — What if RM import fails? Retry policy? Status tracking?
4. **Status transition guards** — Can a rejected recommendation be reopened? (Current answer: no, per replay rules)

## Estimated Tests

- Unit: Rule draft core assembly, status transition validation
- Integration: Draft repository CRUD, export status tracking, audit trail completeness
- Smoke: Full action flow through API (acknowledge -> create draft -> export)
- Cross-repo: RM receives and persists draft with provenance
