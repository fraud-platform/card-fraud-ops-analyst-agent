# Incidents and Rollback

## Incident Severity Levels

- `SEV1`: security breach, data exposure, or critical service outage.
- `SEV2`: major degradation affecting analyst operations.
- `SEV3`: partial degradation with workaround.

## Response Priorities

1. Preserve analyst workflow continuity.
2. Protect data and access boundaries.
3. Restore deterministic evidence availability.
4. Restore optional reasoning capabilities.

## Rollback Controls

- Feature flag kill switches:
  - disable deep mode
  - disable LLM reasoning
  - disable draft export
- Revert to evidence-only recommendation mode.
- Pause continuous mode if dependency instability persists.

## Post-Incident Actions

- Root cause analysis.
- Audit and timeline reconstruction.
- Gate reassessment for affected release stage.
- Update runbooks and tests.
