# Core Health And Readiness Runbook

## Endpoints
- `GET /api/core/health/live`: process liveness probe.
- `GET /api/core/health/ready`: readiness probe with runtime diagnostics.

## Readiness Response Fields
- `ready`: boolean readiness result (`200` when `true`, `503` when `false`).
- `phase_a_status`: bootstrap phase-A status.
- `phase_b_status`: platform runtime aggregate status.
- `critical_platforms`: configured critical platform list.
- `failed_platforms`: critical platforms currently not healthy.
- `reasons`: per-platform degradation reasons.

## Operational Interpretation
- `phase_a_status != healthy`: bootstrap/configuration failure, deployment should not receive traffic.
- `phase_b_status == starting`: platform runtime is warming up; readiness can stay green only within grace period.
- `failed_platforms` non-empty: inspect platform-specific logs and treat as degraded runtime.

## Triage Checklist
1. Check `/api/core/health/ready` payload and identify `failed_platforms`.
2. Correlate platform failure reason with runtime logs for the same platform name.
3. For critical platform clean exits, confirm whether exit was expected shutdown or unexpected runtime stop.
4. Validate timeout/profile settings (`mugen.runtime.profile`, gateway timeout keys, qdrant retry/timeout keys).
5. Roll back or restart only after readiness returns `ready=true` with empty `failed_platforms`.
