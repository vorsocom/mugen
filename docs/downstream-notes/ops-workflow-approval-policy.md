# Ops Workflow Approval Policy

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_workflow` enforces deterministic transition validity and row-version
concurrency but intentionally does not encode business approver rules. The core
actions (`advance`, `approve`, `reject`, `assign_task`) are generic and must be
combined with downstream authorization and policy decisions.

## Decision

- Keep approver eligibility and separation-of-duties rules downstream.
- Resolve policy by tenant + workflow + transition key before approval actions.
- Deny by default when no explicit policy match exists.
- Record policy decision metadata in task/instance action payload or note.

## Core vs Downstream Boundary

- Core responsibilities:
  - Validate allowed state transitions.
  - Create and complete approval tasks for `requires_approval` transitions.
  - Enforce optimistic concurrency via row-version checks.
- Downstream responsibilities:
  - Decide who can approve/reject and who can assign/handoff tasks.
  - Enforce domain-specific constraints (e.g., maker-checker, risk tiering).
  - Maintain auditable policy versions and override workflows.
- Why this boundary:
  - Approval semantics are product- and tenant-specific and change frequently.

## Implementation Sketch

### Data Model

Add downstream policy tables, for example:

- `downstream_workflow_approval_policy`
  - `tenant_id UUID NOT NULL`
  - `workflow_definition_key CITEXT NOT NULL`
  - `transition_key CITEXT NOT NULL`
  - `approver_role_key CITEXT NOT NULL`
  - `min_approvals INTEGER NOT NULL DEFAULT 1`
  - `deny_submitter BOOLEAN NOT NULL DEFAULT false`
  - `is_active BOOLEAN NOT NULL DEFAULT true`
  - `effective_from timestamptz NOT NULL`
  - `effective_to timestamptz NULL`

- `downstream_workflow_approval_binding`
  - maps approver role/group keys to user ids or queues.

### Services / APIs

1. Resolve policy during `advance` for approval-required transitions.
2. Pre-select assignee/queue and call `assign_task` with row-version.
3. Check actor authorization before `approve`/`reject` calls.
4. Store decision trace (`policy_id`, `rule_version`, `reason_code`) in payload.

Use ACP actions on `OpsWorkflowInstances` and `OpsWorkflowTasks`; do not write
core workflow tables directly.

### Operational Notes

- Seed default policies for each tenant/workflow before go-live.
- Version policies with effective windows for zero-downtime rollouts.
- Add an operator override process with explicit audit notes.

## Validation

- Unit tests for policy matching/precedence and deny-by-default behavior.
- Integration tests for authorized vs unauthorized `approve`/`reject`.
- Concurrency test with stale row-version on `assign_task` and `approve`.
- E2E tests for maker-checker constraints on one critical workflow.

## Risks / Open Questions

- Group membership staleness can produce false allow/deny decisions.
- Multi-approval workflows may need additional downstream coordination state.
- Cross-tenant shared role catalogs may complicate policy isolation.
