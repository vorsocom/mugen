# Phase 3 Decisioning Layer Adoption

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-25

## Context

Phase 3 adds a core decisioning layer across `ops_governance`,
`ops_workflow`, and `ops_sla`:

- `ops_governance` now runs a built-in PDP for policy `DocumentJson` DSL and
  emits enriched immutable decision logs.
- `ops_workflow` introduces first-class `DecisionRequest` and
  `DecisionOutcome` primitives and links approval flows to these records.
- `ops_sla` escalation execution now supports real `open_decision` actions.

Downstream services must adopt these primitives without breaking existing
`approve`/`reject` integrations.

## Decision

- Keep current plugin boundaries and entity-set names.
- Preserve existing `approve`/`reject` actions as compatibility wrappers.
- Auto-create a legacy bridge decision request when a pending approval task has
  no linked open decision request.
- Treat non-approval obligations as downstream responsibilities.
- Standardize on policy trace propagation using `TraceId` where available.
- Guarantee approval-request failures are compensated so instance state is not
  persisted as `awaiting_approval` without a linked open decision request.

## Core vs Downstream Boundary

- Core responsibilities:
  - Evaluate policy documents and persist immutable decision evidence.
  - Enforce approval-path decision request lifecycle in workflow actions.
  - Execute SLA escalation `open_decision` actions in core execution loops.
  - Preserve backward compatibility on existing action contracts.
- Downstream responsibilities:
  - Author and govern policy documents per tenant/domain.
  - Execute non-approval obligations (notify, route, redact, external jobs).
  - Enforce business authorization and approver eligibility rules.
  - Operate retries, alerts, and dashboards for decisioning SLOs.
- Why this boundary:
  - Core provides deterministic orchestration and evidence; domain side effects
    remain product-specific.

## Implementation Sketch

### Data Model

- No additional downstream schema is required for baseline adoption.
- Recommended optional downstream telemetry:
  - decision request queue lag (`open` + `due_at`)
  - policy decision distribution by policy/version (`allow/deny/review/warn`)
  - escalation `open_decision` success/failure counters.

### Services / APIs

1. Policy evaluation:
   - call `OpsPolicyDefinitions/{id}/$action/evaluate_policy` with `InputJson`
     and optional `ActorJson`/`TraceId`.
2. Approval transitions:
   - keep using `OpsWorkflowInstances/$action/advance`, `approve`, `reject`.
   - when approval is required, consume linked decision request IDs from
     payloads/events for downstream observability.
3. Explicit decision flows:
   - use `OpsWorkflowDecisionRequests/$action/open|resolve|cancel|expire_overdue`
     for custom review paths.
4. SLA escalations:
   - include `open_decision` action entries in escalation policy actions to open
     human decision requests directly.

### Operational Notes

- Rollout order:
  1. apply Phase 3 core migration;
  2. seed/activate policy document versions per tenant;
  3. enable policy-bound `advance` paths on selected workflows;
  4. enable escalation `open_decision` actions;
  5. monitor decision queue lag and denial/review rates.
- Keep downstream workers idempotent; key by decision request ID when
  triggering side effects.

## Validation

- Unit tests:
  - PDP allow/deny/review/warn decisions and obligation output.
  - workflow decision request lifecycle and approval wrappers.
  - SLA `open_decision` dry-run and execute behavior.
- Integration tests:
  - policy-bound `advance` deny/review/approval branching.
  - escalation action execution result aggregation.
- E2E checks:
  - policy evaluation with obligations
  - decision request open/resolve action path
  - workflow definition + version smoke coverage.

## Risks / Open Questions

- Non-approval obligation execution drift if downstream workers are not aligned
  with obligation schema evolution.
- Decision backlog growth without explicit expire/sweep operations.
- Policy-document quality governance is required to avoid noisy deny/review
  outcomes in production.
