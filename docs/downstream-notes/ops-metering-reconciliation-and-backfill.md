# Ops Metering Reconciliation And Backfill

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Even with idempotent paths, operational drift can occur between
`OpsUsageRecords`, `OpsRatedUsages`, and billing usage events. Downstream teams
need a reconciliation and backfill runbook for integrity and incident recovery.

## Decision

- Reconcile at three stages: ingested -> rated -> billed.
- Use deterministic join keys (`usage_record_id`, billing external ref).
- Backfill with bounded windows and idempotent writes only.
- Preserve a correction audit trail for any void/re-rate workflows.

## Core vs Downstream Boundary

- Core responsibilities:
  - Maintain canonical usage/rated state and billing handoff references.
  - Provide action surfaces for `rate_record` and `void_record`.
- Downstream responsibilities:
  - Schedule reconciliation jobs and define discrepancy thresholds.
  - Trigger correction flows and downstream financial adjustments.
  - Produce operational reports and incident artifacts.
- Why this boundary:
  - Reconciliation cadence and remediation policy are operationally specific.

## Implementation Sketch

### Data Model

Add downstream reconciliation snapshot table, for example:

- `downstream_metering_recon_snapshot`
  - `tenant_id UUID NOT NULL`
  - `snapshot_at timestamptz NOT NULL`
  - `window_start timestamptz NOT NULL`
  - `window_end timestamptz NOT NULL`
  - `ingested_count BIGINT NOT NULL`
  - `rated_count BIGINT NOT NULL`
  - `billed_count BIGINT NOT NULL`
  - `mismatch_count BIGINT NOT NULL`
  - `details JSONB NULL`

### Services / APIs

1. Query records in window from metering and billing views.
2. Compute mismatch categories:
   missing-rated, missing-billing-event, quantity/status mismatch.
3. Enqueue corrective actions:
   re-rate, void-and-recreate, or manual review.
4. Store snapshot and publish ops metrics.

### Operational Notes

- Run frequent short-window recon and daily full-window recon.
- Keep correction batches small and tenant-partitioned.
- Freeze corrective writes during billing close windows where required.

## Validation

- Unit tests for mismatch classifiers.
- Integration tests for backfill idempotency and correction paths.
- E2E drill: inject drift, run recon, confirm expected corrective state.

## Risks / Open Questions

- Financial close timing constraints during large backfills.
- Handling historical policy changes when re-rating old usage.
- Ownership boundary between finance and platform teams for corrections.
