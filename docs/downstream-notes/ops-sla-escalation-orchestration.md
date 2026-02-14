# Ops SLA Escalation Orchestration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_sla` can mark breaches and record breach events, but it does not own
who to notify, where to route work, or how escalation levels map to business
actions.

## Decision

- Implement escalation workers downstream.
- Drive downstream routing/notification from clock state + breach events.
- Use `mark_breached` for immutable breach markers.
- Keep escalation attempts idempotent per `(clock_id, level, window)`.

## Core vs Downstream Boundary

- Core responsibilities:
  - Expose clock state and lifecycle actions.
  - Persist append-only breach event ledger.
- Downstream responsibilities:
  - Decide escalation policy, ownership handoff, and notifications.
  - Call domain-specific ACP/core actions when escalation is triggered.
  - Track escalation attempt outcomes and retries.
- Why this boundary:
  - Escalation policy is operational governance and domain-specific.

## Implementation Sketch

### Data Model

Add downstream execution/trace tables, for example:

- `downstream_sla_escalation_attempt`
  - `tenant_id UUID NOT NULL`
  - `clock_id UUID NOT NULL`
  - `escalation_level INTEGER NOT NULL`
  - `attempt_key CITEXT NOT NULL`
  - `status CITEXT NOT NULL` (`queued`, `applied`, `failed`)
  - `applied_at TIMESTAMPTZ NULL`
  - `error_text TEXT NULL`

### Services / APIs

1. Poll active clocks nearing or past deadlines.
2. For newly breached clocks, call `mark_breached` once.
3. Create downstream escalation attempt row and execute routing logic.
4. Optionally call downstream domain actions (assign, notify, pause pipeline).

### Operational Notes

- Include jitter and dead-letter handling for repeated failures.
- Separate warning notifications from hard escalation actions.
- Build replay-safe workers from attempt ledger state.

## Validation

- Unit tests for escalation policy mapping by level.
- Integration tests for retry + idempotency behavior.
- E2E tests for breach detection -> mark_breached -> downstream action.

## Risks / Open Questions

- Escalation loops may occur without max level/timebox guards.
- High-volume breach storms require rate limiting and batching.
