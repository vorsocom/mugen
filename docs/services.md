# Working with muGen Services

Status: Draft
Last Updated: 2026-02-14
Audience: Core and downstream plugin teams

## Purpose

This document explains how to treat ACP and ACP-derived core plugins as a
shared service control plane for downstream orchestration.

## ACP as the Control Plane

`acp` is the foundational service layer for core plugins. It provides:

- tenant-scoped CRUD and action routing;
- permission object/action registration and enforcement;
- shared row-version concurrency behavior;
- contributor-based runtime binding for plugin resources;
- reusable admin HTTP/API surface used by core plugins.

For tenant invitation lifecycle and authenticated redeem contracts, see
`docs/acp-tenant-invitations.md`.

For ACP RBAC policy semantics (deny-by-default, precedence, bootstrap grants),
see `docs/acp-rbac-policy.md`.

Downstream plugins should compose business orchestration on top of ACP-exposed
resources/actions rather than bypassing them with direct table writes.

## ACP-Derived Core Plugins

The following core plugins are built to register their entities/actions into ACP
and provide reusable platform primitives:

- `audit`: append-only audit records for ACP write/action surfaces.
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
   - Alembic migration checker
   - ACP HTTP E2E template suite
