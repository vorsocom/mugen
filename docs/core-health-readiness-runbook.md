# Core Health And Readiness Runbook

## Endpoints
- `GET /api/core/health/live`: process liveness probe.
- `GET /api/core/health/ready`: readiness probe with runtime diagnostics.

## Readiness Response Fields
- `ready`: boolean readiness result (`200` when `true`, `503` when `false`).
- `phase_a_status`: bootstrap phase-A status.
- `phase_a_blocking_failed_capabilities`: phase-A capability failures that block readiness.
- `phase_a_non_blocking_degraded_capabilities`: degraded optional capabilities visible to operators but non-blocking.
- `phase_b_status`: platform runtime aggregate status.
- `critical_platforms`: configured critical platform list.
- `platform_statuses`: normalized per-platform phase-B status map.
- `platform_errors`: normalized per-platform error map (non-empty errors only).
- `degraded_platforms`: all currently degraded platforms visible to operators.
- `non_critical_degraded_platforms`: degraded platforms outside the critical set.
- `failed_platforms`: critical platforms currently not healthy.
- `reasons`: per-platform degradation reasons.

## Operational Interpretation
- `phase_a_status != healthy`: bootstrap/configuration failure, deployment should not receive traffic.
- Non-empty `phase_a_blocking_failed_capabilities`: treat as not-ready even if phase-A status appears healthy in stale state snapshots.
- Non-empty `phase_a_non_blocking_degraded_capabilities`: investigate and alert, but this does not block readiness by itself.
- `phase_b_status == starting`: platform runtime is warming up; readiness can stay green only within grace period.
- Non-empty `degraded_platforms`: runtime is degraded somewhere, even if not traffic-blocking yet.
- Non-empty `non_critical_degraded_platforms`: investigate promptly; readiness may remain green by design.
- `failed_platforms` non-empty: inspect platform-specific logs and treat as degraded runtime.
- During shutdown, any unresolved phase-B task timeout is fail-closed:
  - `phase_b_status` must remain `degraded` (never forced to `stopped`).
  - `phase_b_error` and platform-specific timeout errors are operator-facing terminal signals.

## Triage Checklist
1. Check `/api/core/health/ready` payload and identify `failed_platforms`.
2. Correlate platform failure reason with runtime logs for the same platform name.
3. For critical platform clean exits, confirm whether exit was expected shutdown or unexpected runtime stop.
4. Validate timeout/profile settings (`mugen.runtime.profile`, `mugen.runtime.provider_readiness_timeout_seconds`, `mugen.runtime.provider_shutdown_timeout_seconds`, `mugen.runtime.shutdown_timeout_seconds`, gateway timeout keys, qdrant retry/timeout keys).
   `mugen.runtime.provider_shutdown_timeout_seconds` and `mugen.runtime.shutdown_timeout_seconds` are required positive values; missing/invalid values must fail bootstrap.
5. Roll back or restart only after readiness returns `ready=true` with empty `failed_platforms`.
6. If shutdown timeout errors persist, treat the instance as not safely stopped and use process-level investigation/remediation before restart.
