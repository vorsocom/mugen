# Phase 2 Execution Core Adoption

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-25

## Context

Phase 2 introduces a core execution chain across existing plugins:

- canonical intake normalization (`channel_orchestration.WorkItems`)
- workflow runtime-lite replay and compensation planning (`ops_workflow`)
- unified SLA clocks with escalation planning and run logging (`ops_sla`)

This phase is additive and keeps existing action/resource surfaces compatible while
adding deterministic replay and escalation diagnostics needed for downstream
adapter execution.

## Decision

- No new plugin is introduced.
- `channel_orchestration` owns canonical `WorkItems` envelope persistence.
- `ops_workflow` owns replay/compensation runtime-lite behavior and
  `ClientActionKey` idempotent transition replay.
- `ops_sla` owns clock definitions/events, `tick`, escalation policy evaluation,
  and escalation run records.
- Escalation side effects remain adapter-driven downstream; core plans and logs.
- `open_decision` is accepted in policy schema but executes as
  `unsupported_action_type`, producing run status `partial`.

## Core vs Downstream Boundary

- Core responsibilities:
  - Normalize intake payloads into canonical `WorkItems` envelopes.
  - Replay and compensate workflow event streams in `plan_only` mode.
  - Emit SLA clock warning/breach events from `tick` and persist escalation run
    diagnostics (`ok`, `partial`, `failed`, `noop`).
- Downstream responsibilities:
  - Execute domain side effects for planned escalation actions through adapters.
  - Interpret run/result diagnostics and perform retries/compensations in domain
    systems.
  - Maintain adapter-specific payload contracts and delivery semantics.

## Implementation Sketch

### Data Model

- `channel_orchestration_work_item`
  - canonical envelope fields: `TraceId`, `Source`, `Participants`, `Content`,
    `Attachments`, `Signals`, `Extractions`, `LinkedCaseId`,
    `LinkedWorkflowInstanceId`.
- `ops_workflow_workflow_event`
  - additive `event_seq` for deterministic ordering.
- `ops_workflow_workflow_transition`
  - additive `compensation_json` spec.
- `ops_workflow_action_dedup`
  - replay-safe action-key ledger keyed by
    `(tenant_id, workflow_instance_id, action_name, client_action_key)`.
- `ops_sla_clock`
  - additive `trace_id`, `clock_definition_id`, `warned_offsets_json`.
- `ops_sla_clock_definition`, `ops_sla_clock_event`
  - unified target/warn definitions and append-only emitted clock events.
- `ops_sla_escalation_policy`, `ops_sla_escalation_run`
  - deterministic trigger/action policy definitions and execution diagnostics.

### Services / APIs

- `WorkItems/$action/create_from_channel`
  - creates or replays canonical envelope row by `TraceId`.
- `WorkItems/{id}/$action/link_to_case`
  - row-version guarded linkage update.
- `WorkItems/{id}/$action/replay`
  - returns canonical stored envelope payload.
- `OpsWorkflowInstances/{id}/$action/replay`
  - folds ordered event stream and reports divergence; optional `repair=false`.
- `OpsWorkflowInstances/{id}/$action/compensate`
  - emits `compensation_requested` + `compensation_planned/failed` events in
    `plan_only` mode.
- `OpsSlaClocks/$action/tick`
  - batch-evaluates running clocks, emits `warned` once per configured offset,
    emits `breached` once per clock.
- `OpsSlaEscalationPolicies/$action/evaluate|execute|test`
  - evaluates deterministic trigger matches, executes run logging, and supports
    sample-policy testing.

### Worker

- `scripts/run_ops_execution_core_worker.py`
  - loops `tick -> escalation.execute` for warning/breach trigger payloads.
  - supports one-shot and interval loop modes.
  - supports tenant targeting, actor override, and dry-run mode.

## Validation

- Unit coverage targets:
  - WorkItem create/link/replay and guard branches.
  - Workflow replay derivation, divergence detection, compensation plan-only
    events, and `ClientActionKey` replay/mismatch behavior.
  - SLA tick warn-once and breach-once semantics.
  - Escalation evaluate/execute/test status transitions and
    `open_decision -> partial` diagnostics.
- Migration checks:
  - alembic graph + revision validation + offline SQL generation.
  - duplicate enum/type safety validation.

## Risks / Open Questions

- Trigger schema variability may require stricter downstream trigger-shape
  contracts over time.
- Phase 2 compensation is plan-only; side-effect execution ownership remains
  external and must be audited independently.
- Escalation throughput can increase run volume significantly and should be
  monitored for retention/cost impact.
