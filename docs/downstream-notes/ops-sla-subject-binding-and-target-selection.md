# Ops SLA Subject Binding and Target Selection

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_sla` stores generic policy, target, calendar, and clock entities, but
it intentionally does not decide which business objects should receive clocks or
how priority/severity values are derived from domain events.

## Decision

- Keep subject-to-policy mapping in downstream code.
- Resolve target buckets (`metric`, `priority`, `severity`) from domain state.
- Create/update clocks through ACP CRUD only.
- Treat mapping as idempotent and recomputable.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store generic SLA entities and lifecycle actions.
  - Compute business-hours deadlines from persisted clock + calendar data.
  - Record breach markers as append-only events.
- Downstream responsibilities:
  - Select when a subject starts SLA tracking.
  - Map subject fields to policy/target buckets.
  - Decide when to stop/close clocks based on domain outcomes.
- Why this boundary:
  - Subject semantics and target mapping are product-specific policy.

## Implementation Sketch

### Data Model

Add downstream mapping/projection tables, for example:

- `downstream_sla_subject_binding`
  - `tenant_id UUID NOT NULL`
  - `subject_namespace CITEXT NOT NULL`
  - `subject_id UUID NOT NULL`
  - `policy_id UUID NOT NULL`
  - `metric CITEXT NOT NULL`
  - `priority CITEXT NULL`
  - `severity CITEXT NULL`
  - `clock_id UUID NULL`
  - unique `(tenant_id, subject_namespace, subject_id, metric)`

### Services / APIs

1. On domain create/triage, resolve policy + target bucket.
2. Create `OpsSlaClocks` row if one does not exist for the binding key.
3. Call `start_clock` action when SLA should begin.
4. On terminal outcomes, call `stop_clock` and mark binding closed.

### Operational Notes

- Use deterministic idempotency keys derived from subject + metric.
- Reconciliation job should backfill missing clocks from historical subjects.
- Keep a checkpoint table for replay safety.

## Validation

- Unit tests for subject-to-target resolution rules.
- Integration tests for idempotent create/start on duplicate events.
- E2E tests for create -> start -> stop over tenant ACP routes.

## Risks / Open Questions

- Missing or stale subject priority/severity may choose wrong target bucket.
- Binding drift can occur if downstream identity keys are mutable.
