# Audit Out-of-Band Write Capture

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core ACP now emits audit events for generic CRUD writes, restore, and `$action`
execution on ACP routes. Downstream systems still perform writes outside ACP
(for example workers, ingestion jobs, reconciliation flows, and direct service
calls), and those writes are not covered automatically.

## Decision

- Treat ACP route emission as the baseline, not full-system coverage.
- Require downstream write paths to emit audit events explicitly.
- Reuse the same normalized fields and operation vocabulary used by ACP
  (`create`, `update`, `delete`, `restore`, `action`).
- Keep downstream capture best-effort and append-only; never mutate prior audit
  rows.

## Core vs Downstream Boundary

- Core responsibilities:
  - Define and persist the canonical `audit_event` record.
  - Emit events from ACP generic write/action execution paths.
- Downstream responsibilities:
  - Emit events for non-ACP writes.
  - Supply plugin-specific metadata in `meta` and `source_plugin`.
- Why this boundary:
  - Core can only reliably capture writes that pass through ACP APIs.
  - Downstream owns execution contexts that bypass ACP.

## Implementation Sketch

### Data Model

- Reuse `mugen.audit_event` without schema forks.
- Store workflow/job identifiers in `meta` (for example `run_id`, `job_name`,
  `batch_id`) to avoid proliferating audit columns.

### Services / APIs

- Add a downstream audit wrapper per plugin (for example
  `<plugin>/service/audit_sink.py`) that accepts domain-level inputs and maps to
  audit fields.
- Call that wrapper at write commit points in background/worker code.
- Populate `request_id` and `correlation_id` from job/trace context when no HTTP
  request exists.

### Operational Notes

- Roll out instrumentation in high-impact write paths first (financial updates,
  status transitions, destructive operations).
- Add a temporary coverage report that lists write handlers still missing audit
  emission.

## Validation

- Unit tests proving each non-ACP write path emits one audit row with expected
  `operation`, `outcome`, and `source_plugin`.
- Integration test that runs a representative worker flow and asserts emitted
  audit records.
- Spot-check dashboards/queries for end-to-end traceability across ACP and
  non-ACP writes.

## Risks / Open Questions

- Duplicate events can occur if downstream retries are not idempotent.
- Missing context propagation can produce weak `correlation_id` values.
- Teams need a standard for `meta` keys to keep cross-plugin analytics stable.
