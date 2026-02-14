# Ops Workflow Escalation and SLA

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_workflow` tracks task assignment/handoff and terminal outcomes but does
not include due dates, breach timers, or escalation policy. Downstream systems
must enforce service-level behavior for long-running approval/work-item tasks.

## Decision

- Keep SLA targets and escalation chains fully downstream.
- Derive task timers from workflow/transition metadata plus tenant policy.
- Run a downstream escalation worker that calls `assign_task` for handoffs.
- Keep escalation idempotent and row-version aware.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store task lifecycle (`open`, `in_progress`, terminal statuses).
  - Track `handoff_count`, assignment fields, and append-only workflow events.
  - Expose generic ACP actions (`assign_task`, `complete_task`).
- Downstream responsibilities:
  - Calculate `due_at`, warning windows, and escalation cadence.
  - Trigger queue/user handoffs on breach.
  - Emit alerts/notifications and on-call routing behavior.
- Why this boundary:
  - SLA contracts and escalation trees are operational policy, not core model.

## Implementation Sketch

### Data Model

Add downstream SLA tracking, for example:

- `downstream_workflow_task_sla`
  - `tenant_id UUID NOT NULL`
  - `workflow_task_id UUID NOT NULL`
  - `target_at timestamptz NOT NULL`
  - `warn_at timestamptz NULL`
  - `breach_at timestamptz NULL`
  - `escalation_level INTEGER NOT NULL DEFAULT 0`
  - `last_escalated_at timestamptz NULL`
  - `status CITEXT NOT NULL` (`active`, `breached`, `closed`)

- `downstream_workflow_task_escalation_event`
  - immutable record of each escalation attempt/outcome.

### Services / APIs

1. On task create/assignment, upsert downstream SLA row.
2. Poll active SLA rows and detect warnings/breaches.
3. For breach, fetch current task row-version and call `assign_task` to handoff.
4. Optionally call `cancel_instance` for hard timeout policies.

Use ACP resources/actions instead of direct writes to core task/instance tables.

### Operational Notes

- Keep escalation worker idempotent by task id + level + time bucket.
- Add jittered retry with backoff for row-version conflicts.
- Exclude terminal tasks from active SLA scans.

## Validation

- Unit tests for SLA deadline calculation and escalation-level progression.
- Integration tests for breach-driven `assign_task` handoffs.
- Conflict tests with concurrent manual assignment and escalation worker.
- E2E tests for warning -> breach -> reassignment path.

## Risks / Open Questions

- Reassignment loops can occur without a max escalation depth.
- Clock skew between worker and DB time may cause early/late escalations.
- Alert fatigue risk if warning thresholds are too aggressive.
