# Ops Metering SLA And Alerting

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Metering reliability is operationally critical. Core exposes data and actions,
but downstream teams need explicit SLAs and alerting policy for ingest, rating,
billing handoff, and correction workflows.

## Decision

- Define stage-specific SLAs for ingest, rate, and billing handoff latency.
- Alert on queue growth, stale records, and elevated action failure rates.
- Track SLOs per tenant and globally.
- Pair technical alerts with runbook links and ownership escalation.

## Core vs Downstream Boundary

- Core responsibilities:
  - Emit canonical state changes through ACP resources/actions.
  - Persist status fields needed for observability queries.
- Downstream responsibilities:
  - Define SLO targets and alert thresholds.
  - Implement metrics pipelines/dashboards and on-call runbooks.
  - Execute incident response and remediation.
- Why this boundary:
  - SLO budgets and on-call policy are org-specific.

## Implementation Sketch

### Data Model

No core schema changes. Optional downstream SLO rollup table:

- `downstream_metering_slo_rollup`
  - `tenant_id UUID NOT NULL`
  - `window_start timestamptz NOT NULL`
  - `window_end timestamptz NOT NULL`
  - `p50_rate_latency_ms BIGINT NOT NULL`
  - `p95_rate_latency_ms BIGINT NOT NULL`
  - `stale_record_count BIGINT NOT NULL`
  - `action_error_count BIGINT NOT NULL`

### Services / APIs

- Build metrics from ACP queryable state:
  - `OpsUsageRecords.status` and `OccurredAt`/`RatedAt`
  - `OpsRatedUsages.status` and billing link fields
- Recommended primary alerts:
  - stale `recorded` usage age > threshold
  - failed/void spike above baseline
  - rating action 5xx or conflict anomaly spikes

### Operational Notes

- Suggested initial targets:
  - P95 ingest-to-rated latency <= 5 minutes
  - unreconciled aged records <= 0.1% per tenant
- Maintain runbooks for:
  - stuck rating queues
  - billing handoff failures
  - replay/reconciliation escalation

## Validation

- Unit tests for latency and stale-record query calculators.
- Integration test with synthetic lag and expected alert trigger.
- On-call game day exercising replay + reconciliation runbooks.

## Risks / Open Questions

- Noisy alerts during large migrations/backfills.
- Tenant-specific burst patterns may require adaptive thresholds.
- Ownership of shared dashboards across platform and finance ops.
