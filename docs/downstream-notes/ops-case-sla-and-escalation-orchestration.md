# Ops Case SLA and Escalation Orchestration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_case` provides lifecycle states and an `escalate` action, but it does
not define deadline calculation, escalation cadence, or paging behavior. Downstream
systems must enforce tenant-specific SLA contracts and escalation workflows.

## Decision

- Keep SLA target calculation and breach policy downstream.
- Drive escalations through ACP `escalate` and `assign` actions only.
- Use DB-time based timers and idempotent escalation keys.
- Separate alerting channels (pager, email, chat) from core state transitions.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store lifecycle timestamps and escalation markers on cases.
  - Append immutable case events for transitions/escalations.
  - Reject invalid transitions using guard checks and row-version constraints.
- Downstream responsibilities:
  - Compute SLA windows by tenant, priority, and calendar.
  - Trigger warning/breach notifications and escalation actions.
  - Route escalated cases to next owner/queue according to policy.
- Why this boundary:
  - SLA commitments and alerting are business policy, not generic case modeling.

## Implementation Sketch

### Data Model

Add downstream SLA tracking tables, for example:

- `downstream_case_sla_state`
  - `tenant_id UUID NOT NULL`
  - `case_id UUID NOT NULL`
  - `target_at timestamptz NOT NULL`
  - `warn_at timestamptz NULL`
  - `breach_at timestamptz NULL`
  - `escalation_level INTEGER NOT NULL DEFAULT 0`
  - `last_escalated_at timestamptz NULL`
  - `status CITEXT NOT NULL` (`active`, `breached`, `closed`)

- `downstream_case_sla_event`
  - immutable event log for warnings, breaches, escalations, and alert delivery.

### Services / APIs

1. On create/triage/reopen, upsert downstream SLA state.
2. Worker scans active SLA states and determines due warnings/breaches.
3. For breach, call `escalate` with latest row-version; optionally call `assign`.
4. Stop SLA timers when core status enters terminal states.

### Operational Notes

- Use UTC and DB clock to avoid app-node skew.
- Add max escalation depth and cooldown windows.
- Expose dashboards for breach rate, MTTA, MTTR, and escalation outcomes.

## Validation

- Unit tests for SLA target calculation and escalation progression.
- Integration tests for conflict retries on concurrent operator updates.
- E2E tests for warn -> breach -> escalate -> reassignment flow.
- Chaos tests for worker restarts and delayed scheduler execution.

## Risks / Open Questions

- Escalation loops if reassignment policy points back to same queue.
- Excessive paging without de-duplication windows.
- SLA pause/resume semantics for `waiting_external` need explicit policy.
