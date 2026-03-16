# Ops Workflow Approval Policy

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-25

## Context

Core `ops_workflow` now includes first-class decision primitives:
`OpsWorkflowDecisionRequests` and append-only `OpsWorkflowDecisionOutcomes`.
`advance` can open linked decision requests for approval paths, while
`approve`/`reject` remain backward compatible wrappers that are decision-aware.

## Decision

- Keep approver eligibility and separation-of-duties rules downstream.
- Resolve policy by tenant + workflow + transition key before approval actions.
- Deny by default when no explicit policy match exists.
- Record policy decision metadata in workflow payloads and decision logs.

## Core vs Downstream Boundary

- Core responsibilities:
  - Validate allowed state transitions.
  - Create and complete approval tasks for `requires_approval` transitions.
  - Open/resolve/cancel decision requests tied to pending approval paths.
  - Keep `approve`/`reject` compatibility while enforcing open decision linkage.
  - Enforce optimistic concurrency via row-version checks.
- Downstream responsibilities:
  - Decide who can approve/reject and who can assign/handoff tasks.
  - Enforce domain-specific constraints (e.g., maker-checker, risk tiering).
  - Maintain policy bindings and override workflows for workflow transitions.
- Why this boundary:
  - Core handles deterministic workflow/decision state transitions; business
    authorization policy remains product- and tenant-specific.

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

1. Resolve policy during `advance` (transition attributes + optional override).
2. On `require_approval` obligations, allow core to open decision requests and
   create pending approval tasks.
3. Check actor authorization before `approve`/`reject` calls.
4. Optionally route explicit review flows via direct `OpsWorkflowDecisionRequests`
   actions (`open`, `resolve`, `cancel`, `expire_overdue`).
5. Store policy and decision trace metadata (`policy_code`, `version`,
   `decision_request_id`) in downstream audit payloads.

Use ACP actions on `OpsWorkflowInstances` and `OpsWorkflowTasks`; do not write
core workflow tables directly.

### Operational Notes

- Seed default policies for each tenant/workflow before go-live.
- Version policies with effective windows for zero-downtime rollouts.
- Add an operator override process with explicit audit notes.

## Validation

- Unit tests for policy matching/precedence and deny-by-default behavior.
- Integration tests for authorized vs unauthorized `approve`/`reject`.
- Decision lifecycle tests for open/resolved/cancelled/expired flows.
- Concurrency test with stale row-version on `assign_task` and `approve`.
- E2E tests for maker-checker constraints on one critical workflow.

## Risks / Open Questions

- Group membership staleness can produce false allow/deny decisions.
- Multi-approval workflows may need additional downstream coordination state.
- Cross-tenant shared role catalogs may complicate policy isolation.
- Escalating decision-request volume can require explicit expiry/sweeper jobs.
