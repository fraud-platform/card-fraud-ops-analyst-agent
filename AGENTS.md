# agents.md

Updated: 2026-02-23

## Current Status

**29/31 E2E quality pass · 31/31 COMPLETED · 210 tests · 0 lint**

## Latest Outputs

- Matrix report: `htmlcov/e2e-31-matrix-report-after-docker-fix.json`
- HTML report: `htmlcov/e2e-scenarios-report.html`
- Stage audit: `htmlcov/stage-audit-report.json`

## Open Quality Issues (not failures)

| Issue | Count | Description |
|---|---|---|
| `fraud_underclassified_low` | 2/13 | velocity_burst scenarios get LOW from LLM despite high-signal fraud |

## Fixed Quality Issues

| Issue | Was | Fixed | Fix |
|---|---|---|---|
| `no_fraud_overescalated` | 6/9 | 0/9 | recommendation_tool now trusts reasoning risk_level bidirectionally |
| `summary_recommendation_contradiction` | 3/31 | 0/31 | resolved by same severity fix |

## Next Work

- Investigate `fraud_underclassified_low` (2 velocity_burst scenarios): LLM returns LOW — check if velocity_snapshot data is populated in seed, or prompt needs stronger velocity framing
- Latency optimization: p95 ~80s worst case — consider parallel tool execution
