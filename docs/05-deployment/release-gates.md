# Release Gates

## Gate 0 - Architecture Freeze

Criteria:
- ADRs approved.
- API and schema contracts reviewed cross-repo.
- Source-of-truth and autonomy boundaries locked.

## Gate 1 - Deterministic Evidence Integrity

Criteria:
- Deterministic feature pipeline validated.
- Replay/idempotency scenarios pass.
- Evidence lineage completeness validated.

## Gate 2 - Security and Data Governance

Criteria:
- Scope-based authz tests pass.
- Prompt guard and redaction tests pass.
- Audit immutability checks pass.

## Gate 3 - Analyst UX Validation

Criteria:
- Portal integration scenarios pass.
- Analysts can acknowledge/reject and create draft packages.
- Human final review checkpoints visible and enforced.

## Gate 4 - Pilot Readiness

Criteria:
- Performance and reliability SLOs met.
- Runbooks and dashboards complete.
- Dependency failure handling validated.

## Gate 5 - Production Enablement

Criteria:
- KPI baseline and target thresholds defined.
- Rollback plan signed off.
- Cross-repo owner approvals completed.

## Mandatory Blocking Rule

No implementation promotion past a gate if any P0 acceptance test is failing.
