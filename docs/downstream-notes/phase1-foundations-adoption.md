# Phase 1 Foundations Adoption

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-25

## Context

Phase 1 adds core control-plane primitives for idempotency, schema contracts,
correlation graphing, and business-trace observability. Downstream adapters and
workers need explicit usage contracts to adopt these features safely without
guessing header conventions, metadata shape, or rollout sequencing.

## Decision

- Downstream producers adopt ACP idempotency using `X-Idempotency-Key` first,
  with optional `X-Idempotency-Scope` and `X-Idempotency-Request-Hash`.
- Parent linkage for correlation graphing uses audit `meta.ParentEntitySet` and
  `meta.ParentEntityId` when parent-child operations are known.
- Schema registry rollout starts in audit-only mode (`enforce_bindings=false`),
  then progresses to per-tenant enforcement after payload coverage review.
- Business-trace persistence remains disabled by default and is enabled
  environment-by-environment with explicit row-growth monitoring.

## Core vs Downstream Boundary

- Core responsibilities:
  - Persist and resolve dedup ledger records, schema definitions/bindings,
    correlation links, and business-trace events.
  - Parse `traceparent` and preserve existing correlation header fallback.
  - Enforce schema bindings only when configured (`acp.schema_registry`).
- Downstream responsibilities:
  - Generate stable idempotency keys per business command/retry domain.
  - Populate parent metadata in action `meta` when cross-entity lineage exists.
  - Publish and version payload schemas owned by downstream contracts.
  - Drive feature toggles and rollout sequencing per tenant/environment.
- Why this boundary:
  - Core supplies reusable primitives; downstream owns business semantics and
    producer discipline.

## Implementation Sketch

### Data Model

- No downstream schema changes are required to start.
- Optional downstream telemetry can aggregate:
  - dedup acquire decisions (`acquired`, `replay`, `in_progress`, `conflict`)
  - schema validation failure reasons
  - business-trace truncation counts.

### Services / APIs

- Idempotency usage pattern:
  - set `X-Idempotency-Key` on ACP create/action requests
  - optionally set `X-Idempotency-Scope` to avoid cross-command collisions
  - optionally set `X-Idempotency-Request-Hash` when producer canonicalization
    must be deterministic across language runtimes.
- Correlation parent metadata pattern:
  - include `ParentEntitySet` and `ParentEntityId` in audit `meta` when a
    request operates on a child record.
- Schema binding rollout pattern:
  - create schema definitions and bindings
  - run `Schemas/$action/validate` and `Schemas/$action/coerce` in preflight
  - enable enforcement after observed validation pass rates are acceptable.

### Operational Notes

- Rollout order:
  1. apply migrations;
  2. deploy code with `enforce_bindings=false` and `audit.biz_trace.enabled=false`;
  3. enable producer idempotency headers on a subset of traffic;
  4. enable business trace in one environment and monitor retention/truncation;
  5. enable schema-binding enforcement per tenant.

## Validation

- Unit and E2E checks:
  - idempotent replay fidelity (status/body/header)
  - schema validate/coerce and activation transitions
  - correlation link resolution graph shape
  - business-trace event redaction and truncation.
- Migration checks:
  - quick alembic checker pass
  - disposable roundtrip (`upgrade head` + `downgrade base`).

## Risks / Open Questions

- Producer-side key quality can cause over-collapsing if scope design is weak.
- Enabling schema enforcement too early may block legacy payload paths.
- Business-trace volume may grow rapidly under high action throughput if not
  monitored and bounded.
