# Knowledge Pack Observability

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Downstream retrieval correctness depends on projection sync, ranking behavior,
and strict scope filtering. Observability must detect drift, stale data, and
scope leakage early.

## Decision

- Instrument projection and retrieval with shared telemetry dimensions.
- Track freshness, correctness, and latency as first-class SLOs.
- Emit structured logs for audit-heavy troubleshooting.
- Add alerts for scope-leak indicators and synchronization lag.

## Core vs Downstream Boundary

- Core responsibilities:
  - Expose authoritative entity IDs and lifecycle transitions.
  - Provide workflow status used as validation source.
- Downstream responsibilities:
  - Capture metrics/logs/traces around indexing and querying.
  - Define alerts and dashboards.
  - Build drift detection jobs.
- Why this boundary:
  - Telemetry stack and SLO targets vary by downstream service ownership.

## Implementation Sketch

### Data Model

No required schema changes, but include these fields in telemetry events:

- `tenant_id`
- `knowledge_pack_id`
- `knowledge_pack_version_id`
- `knowledge_entry_revision_id`
- `channel`
- `locale`
- `ranking_policy_version`
- `index_version`

### Services / APIs

Recommended metrics:

- `kp_projection_lag_seconds`
- `kp_projection_events_processed_total`
- `kp_projection_dead_letter_total`
- `kp_query_latency_ms`
- `kp_query_zero_results_total`
- `kp_scope_mismatch_total`

Recommended logs:

- Query hash and filters applied
- Candidate counts before/after scope filtering
- Top result IDs and scores

### Operational Notes

- Create dashboards split by tenant and locale.
- Add anomaly detection on sudden zero-result spikes.
- Keep trace sampling high enough for low-volume tenants.

## Validation

- Synthetic checks for publish -> searchable latency SLO.
- Drift job compares published revision counts vs index counts.
- Alert-fire drill for dead-letter queue growth.
- Security test confirming scope mismatch metric stays zero.

## Risks / Open Questions

- High-cardinality labels increasing metric costs.
- Logging retention requirements for governance audits.
- Sampling strategy for accurate low-traffic tenant visibility.
