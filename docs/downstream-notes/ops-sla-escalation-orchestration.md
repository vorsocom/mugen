# Ops SLA Escalation Orchestration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-25

## Context

Core `ops_sla` can mark breaches and record breach events. With Phase 3,
escalation `open_decision` actions are now executable in core and open
`OpsWorkflowDecisionRequests` directly.

## Decision

- Implement escalation workers downstream.
- Drive downstream routing/notification from clock state + breach events.
- Use core `open_decision` execution for human-in-the-loop escalation gates.
- Use `mark_breached` for immutable breach markers.
- Keep escalation attempts idempotent per `(clock_id, level, window)`.

## Core vs Downstream Boundary

- Core responsibilities:
  - Expose clock state and lifecycle actions.
  - Persist append-only breach event ledger.
  - Execute `open_decision` escalation actions (or `planned` in dry-run).
  - Return per-action diagnostics (`opened` or `failed_open_decision`).
- Downstream responsibilities:
  - Decide escalation policy, ownership handoff, and notifications.
  - Call additional domain-specific ACP/core actions when escalation is triggered.
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
3. Execute escalation actions:
   - `open_decision` via core action execution,
   - downstream domain actions (assign, notify, pause pipeline) as needed.
4. Create downstream escalation attempt row and track outcomes/retries.

### Operational Notes

- Include jitter and dead-letter handling for repeated failures.
- Separate warning notifications from hard escalation actions.
- Build replay-safe workers from attempt ledger state.

## Validation

- Unit tests for escalation policy mapping by level.
- Integration tests for `open_decision` dry-run/execute and retry behavior.
- E2E tests for breach detection -> mark_breached -> open_decision.

## Risks / Open Questions

- Escalation loops may occur without max level/timebox guards.
- High-volume breach storms require rate limiting and batching.
- Decision-request creation failures should be retried with bounded backoff.
