# ACP Audit Lifecycle

Status: Draft
Last Updated: 2026-02-24

## Scope

This document defines ACP action contracts for audit integrity and lifecycle
operations exposed through `AuditEvents`.

`AuditEvents` uses optional tenant scope (`TenantId` nullable), so both route
families are supported:

- non-tenant routes
- tenant routes

## Routes

Entity actions:

- `POST /api/core/acp/v1/AuditEvents/{id}/$action/place_legal_hold`
- `POST /api/core/acp/v1/AuditEvents/{id}/$action/release_legal_hold`
- `POST /api/core/acp/v1/AuditEvents/{id}/$action/redact`
- `POST /api/core/acp/v1/AuditEvents/{id}/$action/tombstone`
- `POST /api/core/acp/v1/tenants/{tenant_id}/AuditEvents/{id}/$action/<action>`

Entity-set actions:

- `POST /api/core/acp/v1/AuditEvents/$action/run_lifecycle`
- `POST /api/core/acp/v1/AuditEvents/$action/verify_chain`
- `POST /api/core/acp/v1/AuditEvents/$action/seal_backlog`
- `POST /api/core/acp/v1/tenants/{tenant_id}/AuditEvents/$action/<action>`

## Request Contracts

Entity actions (`place_legal_hold`, `release_legal_hold`, `redact`, `tombstone`)
require:

- `RowVersion` (required)
- `Reason` (required)
- `LegalHoldUntil` (optional, hold only)
- `PurgeAfterDays` (optional, tombstone only)

`run_lifecycle` request:

- `BatchSize` (optional)
- `MaxBatches` (optional)
- `DryRun` (optional, default `false`)
- `NowOverride` (optional, test-only)
- `Phases` (optional subset of `seal_backlog`, `redact_due`,
  `tombstone_expired`, `purge_due`)

`verify_chain` request:

- `FromOccurredAt` (optional)
- `ToOccurredAt` (optional)
- `MaxRows` (optional)
- `RequireClean` (optional, default `false`)

`seal_backlog` request:

- `BatchSize` (optional)
- `MaxBatches` (optional)

## Response Contracts

Entity actions:

- `204` success (idempotent where applicable)
- `404` target row missing
- `409` row-version conflict or lifecycle-state conflict
- `500` storage/SQL failure

`run_lifecycle`:

- `200` summary payload with per-phase counts

`verify_chain`:

- `200` payload includes `IsValid`, `MismatchCount`, `Mismatches`
- `409` when `RequireClean=true` and mismatches are detected

`seal_backlog`:

- `200` payload includes `RowsSealed`, `RemainingCount`, `Batches`

## Integrity Semantics

- Each audit row is sealed with HMAC-SHA256 chain metadata:
  `scope_key`, `scope_seq`, `prev_entry_hash`, `entry_hash`, `hash_key_id`.
- Hash payload uses immutable event facts and snapshot hashes
  (`before_snapshot_hash`, `after_snapshot_hash`) rather than raw snapshot
  payloads.
- Redaction clears snapshots while preserving snapshot hashes, so chain
  verification remains valid.

## Worker Path

Lifecycle phases can be run by ACP action calls or via script:

- `scripts/run_audit_lifecycle_worker.py`

The script supports one-shot and looped execution and reuses the same lifecycle
action contract.
