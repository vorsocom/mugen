# Audit Retention and Redaction Operations

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core stores retention and redaction policy fields on audit records
(`retention_until`, `redaction_due_at`, `redacted_at`, `redaction_reason`) and
now includes first-class lifecycle execution (`run_lifecycle`, `seal_backlog`)
plus a worker script path.

## Decision

- Use core lifecycle phases (`redact_due`, `tombstone_expired`, `purge_due`)
  for retention/redaction operations.
- Redact snapshots first, then tombstone and purge expired rows per policy.
- Keep immutable audit semantics: lifecycle jobs may redact or delete rows based
  on policy windows, but should not rewrite historical business facts.
- Record lifecycle actions with explicit reason codes.

## Core vs Downstream Boundary

- Core responsibilities:
  - Persist policy timing fields and redaction markers on audit rows.
  - Enforce DB immutability/delete guardrails.
  - Provide lifecycle actions and worker-compatible execution path.
- Downstream responsibilities:
  - Schedule lifecycle execution by environment policy.
  - Define legal/compliance policy windows by environment/tenant.
  - Produce operational telemetry and alerting for job failures.
- Why this boundary:
  - Policy enforcement and legal obligations differ by deployment and tenant.

## Implementation Sketch

### Data Model

- Use existing `audit_event` fields:
  - Redaction step: clear `before_snapshot`/`after_snapshot`, set `redacted_at`
    and `redaction_reason`.
  - Retention step: delete rows where `retention_until` is exceeded.
- Optional downstream control table for job checkpoints and run history.

### Services / APIs

- Use core maintenance phases:
  1. `seal_backlog`
  2. `redact_due`
  3. `tombstone_expired`
  4. `purge_due`
- Make each phase idempotent and bounded by batch size.
- Publish metrics (rows scanned/redacted/deleted, lag, failures).

### Operational Notes

- Start with dry-run mode in lower environments.
- Roll out with conservative batch sizes to avoid load spikes.
- Keep an emergency pause switch for lifecycle jobs.

## Validation

- Unit tests for selection predicates and update/delete behavior.
- Integration test for redaction then purge over seeded audit rows.
- Operational acceptance: alerting fires when lag or failure thresholds exceed
  policy.

## Risks / Open Questions

- Incorrect policy windows can cause premature deletion.
- Large backlogs may require partitioning or archival before purge.
- Cross-tenant policy variance needs clear config precedence rules.
