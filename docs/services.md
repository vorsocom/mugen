# Working with muGen Services

Status: Draft
Last Updated: 2026-03-09
Audience: Core and downstream plugin teams

## Purpose

This document explains how to treat ACP and ACP-derived core plugins as a
shared service control plane for downstream orchestration.

## Core Architecture Boundary Contract

The following layer rules are considered hard constraints for `mugen/core`:

- Domain/use-case code stays pure and cannot import adapters, DI, runtime/bootstrap orchestration, or Quart.
- Contracts define ports and cannot import implementation packages.
- Bootstrap/orchestration composes domain + contracts + DI, but does not directly import concrete adapters.
- Adapter layers (clients/gateways) cannot import the API layer.

These rules are enforced by architecture-boundary tests and should be preserved during service changes.

## Shared Messaging Ingress Service

External messaging platforms now share one durable ingress foundation instead of
each platform owning its own inbox/dedup/dead-letter runtime.

The `ingress` service is responsible for:

- normalizing transport-specific payloads into one canonical ingress envelope;
- staging inbound rows durably before business processing;
- maintaining shared dedupe, dead-letter, and checkpoint tables;
- leasing and dispatching queued ingress work through normalized IPC commands.

This applies to:

- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

It does not apply to `web`, which keeps its existing queue/stream contract.

See [Messaging Ingress Contract](./messaging-ingress-contract.md) for the
shared envelope, table, worker, and replay semantics.

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

## Live Platform Runtime Reload

ACP now also exposes an admin action for reconciling active multi-profile
platform runtimes without a full process restart.

- entity set: `SystemFlags`
- action: `reloadPlatformProfiles`

Behavior:

- rereads and validates the active config file;
- reloads changed runtime profiles for active profiled messaging platforms;
- leaves unchanged platforms untouched;
- rolls back reloaded platforms if a later reload step fails;
- rejects platform activation changes, which still require restart.

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

## Context Engine Service Boundary

Core messaging no longer treats context assembly and retrieval as CTX/RAG
extension categories. That split has been replaced by a dedicated
`IContextEngine` runtime service with a two-phase contract:

- `prepare_turn(ContextTurnRequest) -> PreparedContextTurn`
- `commit_turn(request, prepared, completion, final_user_responses, outcome) -> ContextCommitResult`

The default engine composes typed collaborators behind ports:

- contributors emit typed `ContextCandidate` artifacts with provenance;
- guards redact or veto artifacts before compilation;
- rankers score candidates without owning storage;
- caches provide working-set, retrieval, and prefix-hint storage;
- trace sinks record selected and dropped artifacts plus commit outcomes;
- state and memory writers persist bounded state and long-term writeback.

The compiled output targets the existing normalized completion contract
(`CompletionRequest` / `CompletionMessage`) instead of provider-specific prompt
logic.

Contract guarantee lives in `docs/context-engine-design.md`.
Collaborator authoring and current reference-plugin details live in
`docs/context-engine-authoring.md`.
Operational runtime examples across prepare and commit live in
`docs/context-engine-user-stories.md`.
For production debugging of selected/dropped artifacts, fallback-global
behavior, commit-token failures, and trace interpretation, see
`docs/context-engine-debugging-playbook.md`.

## Context Engine Plugin

The core `context_engine` plugin is both a runtime-composition layer and an ACP
control-plane contributor.

Runtime responsibilities:

- register default contributors for persona/policy, state, recent turns,
  knowledge packs, orchestration overlays, case state, audit traces, and memory;
- register renderers for the stable lane buckets;
- register state store, commit store, cache, memory writer, and trace sink
  services;
- enforce single-owner runtime composition for policy resolver, state store,
  commit store, memory writer, and cache;
- keep all runtime records tenant-scoped and provenance-aware.

ACP-managed resources:

- `ContextProfiles`
- `ContextPolicies`
- `ContextContributorBindings`
- `ContextSourceBindings`
- `ContextTracePolicies`

High-churn runtime internals stay behind service/storage layers rather than ACP
CRUD resources. The plugin is the reference implementation for that runtime,
not the complete service contract.

## Tenant Fallback Policy

`ContextScope.tenant_id` is mandatory for every turn. When ingress routing
cannot positively resolve a tenant, muGen may fall back to `GLOBAL_TENANT_ID`
only for these cases:

- missing identifier
- missing binding
- no tenant-routing subsystem for the platform path

Explicit negative routing outcomes still fail closed. Fallback-global turns are
recorded in `ingress_metadata["tenant_resolution"]` and in context traces so
operators can distinguish `resolved` from `fallback_global` behavior.

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
