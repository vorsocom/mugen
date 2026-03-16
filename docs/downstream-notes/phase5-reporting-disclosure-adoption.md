# Phase 5 Reporting + Disclosure Adoption

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-26

## Context

Phase 5 extends `ops_reporting` with two RFC surfaces:

- RFC-0012: signed, reproducible report snapshot provenance.
- RFC-0013: deterministic export jobs/items with proof blocks and optional
  policy gating.

No new plugin is introduced; all additions remain in `ops_reporting`.

## Locked Decisions

- Snapshot manifest hashing uses canonical JSON + SHA-256.
- Snapshot signing is optional (`Sign=false` default).
- Export signing uses the same `ops_reporting_signing` key purpose and defaults
  to enabled (`Sign=true` on `build_export`).
- Signing algorithm for Phase 5 is `hmac-sha256`.
- Export build is synchronous action execution (no background worker).
- Export proofs include snapshot verification and optional
  `AuditEvents/$action/verify_chain` summary.
- Optional policy gating runs only when `PolicyDefinitionId` is provided on
  `create_export`.

## Core Surface Changes

- `OpsReportingReportSnapshots`:
  - `generate_snapshot` payload adds: `TraceId`, `Sign`, `SignatureKeyId`,
    `ProvenanceRefsJson`.
  - new action: `verify_snapshot` (`RequireClean`).
- new entity sets:
  - `OpsReportingExportJobs`
  - `OpsReportingExportItems` (read-only item ledger)
- `OpsReportingExportJobs` actions:
  - `create_export`
  - `build_export`
  - `verify_export`

## Migration Summary

Schema migration:
`a6b8c0d2e4f6_phase5_reporting_disclosure_schema`

- extends `mugen.ops_reporting_report_snapshot` with:
  - `trace_id`
  - `provenance_json`
  - `manifest_hash`
  - `signature_json`
- creates enum `mugen.ops_reporting_export_job_status`
  (`queued|running|completed|failed`)
- creates:
  - `mugen.ops_reporting_export_job`
  - `mugen.ops_reporting_export_item`
- adds tenant/status/trace and item-ledger indexes for deterministic lookup and
  verification.

ACP reseed migration:
`b7c9d1e3f5a7_reseed_acp_for_phase5_reporting_disclosure`

- re-applies manifests so new entity sets/actions are seeded.

## Backward Compatibility

- Existing Phase 1-4 routes and actions are unchanged.
- Existing snapshot lifecycle (`generate/publish/archive`) remains valid.
- Unsigned snapshots remain supported.
- Exports are additive and do not alter existing reporting CRUD semantics.

## Operational Rollout

1. Apply schema migration.
2. Apply ACP reseed migration.
3. Provision `KeyRefs` for purpose `ops_reporting_signing` (tenant-specific and/or global fallback).
4. Enable snapshot signing for selected tenants/jobs.
5. Roll out `report_snapshot_pack` export usage first; extend to
   `compliance_pack` after baseline stability.
6. Monitor signing resolution failures and verification mismatch rates.

## Validation Expectations

- Snapshot generation persists deterministic provenance + manifest hash.
- `verify_snapshot` detects tamper on summary/provenance/hash/signature.
- Export build persists deterministic item order + content hashes.
- `verify_export` recomputes item/manifest/signature checks and supports
  `RequireClean` hard-fail semantics.
- Policy gate deny/review decisions block `create_export` with `409`.

## Out of Scope

- Background export worker orchestration.
- Binary bundle storage in core DB (metadata-first model remains).
- Non-`hmac-sha256` signing algorithms.
