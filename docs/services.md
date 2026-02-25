# Working with muGen Services

Status: Draft
Last Updated: 2026-02-25
Audience: Core and downstream plugin teams

## Purpose

This document explains how to treat ACP and ACP-derived core plugins as a
shared service control plane for downstream orchestration.

## ACP as the Control Plane

`acp` is the foundational service layer for core plugins. It provides:

- tenant-scoped CRUD and action routing;
- permission object/action registration and enforcement;
- shared row-version concurrency behavior;
- opt-in request idempotency via `X-Idempotency-Key` with ACP dedup ledger replay;
- generic schema registry and optional payload-binding enforcement gates;
- contributor-based runtime binding for plugin resources;
- reusable admin HTTP/API surface used by core plugins.

For tenant invitation lifecycle and authenticated redeem contracts, see
`docs/acp-tenant-invitations.md`.

For ACP RBAC policy semantics (deny-by-default, precedence, bootstrap grants),
see `docs/acp-rbac-policy.md`.

Downstream plugins should compose business orchestration on top of ACP-exposed
resources/actions rather than bypassing them with direct table writes.

For schema ownership and migration isolation between core and downstream
plugins, see `docs/migration-track-separation.md`.

## ACP-Derived Core Plugins

The following core plugins are built to register their entities/actions into ACP
and provide reusable platform primitives:

- `audit`: tamper-evident audit records with hash-chain verification and
  lifecycle controls (legal hold, redact, tombstone, purge), plus correlation
  graph links and business-trace observability timeline events.
- `billing`: account/product/price/subscription/usage/invoice/payment primitives.
- `channel_orchestration`: intake, routing, throttle, blocklist, and fallback.
- `knowledge_pack`: versioned knowledge content lifecycle and retrieval metadata.
- `ops_case`: canonical case lifecycle, assignment, escalation, and timeline.
- `ops_governance`: consent/delegation/policy/retention metadata and actions.
- `ops_metering`: usage capture/rating/session primitives.
- `ops_reporting`: metric definition, aggregation, and snapshot lifecycle.
- `ops_sla`: business-hour-aware clocks and breach markers.
- `ops_vpn`: operations vendor registry and lifecycle scorecard primitives.
- `ops_workflow`: workflow definitions, instances, tasks, and approvals.

## Planning Guidance

For downstream business-case planning:

1. Start with the orchestration matrix:
   `docs/downstream-notes/acp-derivatives-orchestration-matrix.md`.
2. Select the plugin note index for each involved domain under
   `docs/downstream-notes`.
3. Define downstream-only policy/execution layers without changing core plugin
   contracts.
4. Validate with standard checks:
   - ACP style checker
   - Alembic migration checker (per track)
   - ACP HTTP E2E template suite

## Phase 1 Foundations

Phase 1 introduces four core-only control-plane primitives:

- ACP `DedupRecords`: shared idempotency ledger with acquire/commit/sweep
  actions and replay envelopes.
- ACP `Schemas` and `SchemaBindings`: generic schema registry with validate,
  coerce (defaults only), and activate-version actions.
- Audit `AuditCorrelationLinks`: trace/correlation/entity graph edges for
  resolve-trace projections.
- Audit `AuditBizTraceEvents`: request-lifecycle timeline events for
  inspect-trace diagnostics.

Downstream rollout guidance is documented in:
`docs/downstream-notes/phase1-foundations-adoption.md`.

## Phase 3 Decisioning Layer

Phase 3 adds decisioning primitives in existing core plugins:

- `ops_governance`:
  - PDP-based `evaluate_policy` with policy document DSL evaluation,
    obligations, and enriched decision logs.
  - `activate_version` action for single-active policy version control.
- `ops_workflow`:
  - new `OpsWorkflowDecisionRequests` and `OpsWorkflowDecisionOutcomes`
    resources.
  - approval paths in `advance`/`approve`/`reject` now integrate with linked
    decision requests while preserving backward compatibility.
- `ops_sla`:
  - escalation `open_decision` is executable in core (dry-run `planned`,
    execute `opened`).

Downstream rollout guidance is documented in:
`docs/downstream-notes/phase3-decisioning-layer-adoption.md`.
