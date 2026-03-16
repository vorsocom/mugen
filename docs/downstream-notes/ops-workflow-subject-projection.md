# Ops Workflow Subject Projection

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_workflow` exposes generic runtime state (`WorkflowInstance`,
`WorkflowTask`, `WorkflowEvent`) and optional subject fields
(`subject_namespace`, `subject_id`, `subject_ref`). Core does not project those
states into downstream domain aggregates or reporting views.

## Decision

- Keep domain-specific projection/read models downstream.
- Use `WorkflowEvent` as the canonical append-only source for projections.
- Maintain replayable, checkpointed processors per tenant.
- Never mutate downstream business state by writing core tables directly.

## Core vs Downstream Boundary

- Core responsibilities:
  - Persist workflow lifecycle entities and append-only event timeline.
  - Emit deterministic transition/approval/task events.
  - Provide ACP CRUD/action surface for workflow operations.
- Downstream responsibilities:
  - Map workflow status/state to domain aggregate status.
  - Build searchable/reporting projections keyed by domain subject.
  - Run replay/backfill processors and manage projection checkpoints.
- Why this boundary:
  - Domain model semantics vary by application and cannot be standardized in core.

## Implementation Sketch

### Data Model

Add downstream projection tables, for example:

- `downstream_workflow_subject_projection`
  - `tenant_id UUID NOT NULL`
  - `subject_namespace CITEXT NOT NULL`
  - `subject_id UUID NOT NULL`
  - `workflow_instance_id UUID NOT NULL`
  - `workflow_status CITEXT NOT NULL`
  - `current_state_key CITEXT NULL`
  - `pending_task_id UUID NULL`
  - `last_event_at timestamptz NOT NULL`
  - `last_event_id UUID NOT NULL`

- `downstream_workflow_projection_checkpoint`
  - one row per projector partition with last processed event cursor.

### Services / APIs

1. Read `OpsWorkflowEvents` ordered by `(occurred_at, id)` after checkpoint.
2. Resolve related instance/task/state data through ACP reads as needed.
3. Upsert subject projection rows in a transaction with checkpoint update.
4. Expose domain-facing read API from downstream projection table.

### Operational Notes

- Support full replay for tenant bootstrap and schema changes.
- Partition projector workload by tenant or workflow definition key.
- Keep projector handlers idempotent on event id.

## Validation

- Unit tests for each event-type-to-projection mapping.
- Replay tests proving deterministic final projection from same event stream.
- Backfill test for large event windows and checkpoint resume behavior.
- Contract test ensuring projection ignores unknown/new event payload fields.

## Risks / Open Questions

- Late-arriving events can cause temporary projection drift.
- Large tenants may require partitioned/rebalanced projector workers.
- Projection schema evolution requires careful replay compatibility controls.
