# Ops Case Routing and Assignment Policy

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_case` intentionally exposes generic assignment fields (`owner_user_id`,
`queue_name`) and actions (`assign`, `triage`) but does not define tenant- or
channel-specific routing policy. Downstream systems need deterministic rules for
initial queue selection, re-routing, and manual override precedence.

## Decision

- Keep routing rules fully downstream and data-driven.
- Treat core `assign` action as the only write path for owner/queue changes.
- Apply deterministic precedence: explicit override > policy match > fallback queue.
- Persist policy decision metadata in downstream tables, not in core schema.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store assignment state and append assignment history/event rows.
  - Enforce action-level row-version conflict checks.
  - Expose generic ACP actions for transitions and assignment.
- Downstream responsibilities:
  - Resolve routing target from source channel, case attributes, and tenant policy.
  - Implement queue balancing (skills, load, business hours).
  - Decide conflict behavior when manual and automated assignment race.
- Why this boundary:
  - Routing behavior is operational policy that varies per tenant and channel.

## Implementation Sketch

### Data Model

Add downstream policy tables, for example:

- `downstream_case_routing_policy`
  - `tenant_id UUID NOT NULL`
  - `priority INTEGER NOT NULL`
  - `match_expr JSONB NOT NULL`
  - `target_queue CITEXT NULL`
  - `target_owner_user_id UUID NULL`
  - `enabled BOOLEAN NOT NULL DEFAULT true`

- `downstream_case_routing_decision`
  - immutable log of input snapshot, matched rule, and selected target.

### Services / APIs

1. On intake or triage completion, evaluate routing policy rules.
2. Call ACP `assign` action on `OpsCases/{id}` with current row-version.
3. On `409`, reload case and re-evaluate if routing still applies.
4. Keep manual operator assignment as a higher-precedence override.

### Operational Notes

- Make policy evaluation idempotent by `(tenant_id, case_id, policy_version)`.
- Add jitter/backoff on repeated row-version conflicts.
- Track auto-assignment rate and conflict rate for policy tuning.

## Validation

- Unit tests for precedence and rule matching.
- Integration tests for race between manual assign and policy worker.
- E2E tests for intake -> triage -> assign path with expected queue outcomes.
- Metric checks: assignment latency and conflict retries.

## Risks / Open Questions

- Overly broad rules can cause queue starvation.
- Manual override semantics need explicit TTL/reset policy.
- Cross-tenant shared queue patterns need clear isolation constraints.
