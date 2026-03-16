# Phase 4 Security + Compliance Substrate

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-26

## Context

Phase 4 introduces core security/compliance primitives across existing plugins:
`acp`, `audit`, and `ops_governance`.

- RFC-0009: key management registry + provider abstraction.
- RFC-0017: plugin capability grants + runtime sandbox enforcement.
- RFC-0007: evidence metadata and chain-of-custody lifecycle.
- RFC-0008: retention/legal-hold lifecycle orchestration.

No new plugin is introduced in this phase.

## Locked Decisions

- `plugin_key` for grants is the plugin `namespace` from configuration.
- Capability resolution order is tenant grant first, then
  `GLOBAL_TENANT_ID` fallback.
- Capability enforcement mode defaults to `enforce` for actions that declare
  `required_capabilities`.
- Lifecycle orchestration scope is `AuditEvent` and `EvidenceBlob` only.
- `EvidenceBlob` is metadata-first (`storage_uri` + hash material), not
  in-database binary storage.
- A general tenant-scoped managed-file/blob primitive is intentionally deferred.
  If a shared cross-domain need emerges later, it should land as a separate
  ACP-aligned plugin rather than ACP core.
- Existing `DataHandlingRecord.EvidenceRef` remains supported;
  `EvidenceBlobId` is additive.

## Core Surface Changes

- ACP:
  - new `KeyRefs` entity set with actions:
    - `rotate` (entity-set and tenant-scoped)
    - `retire` (entity action)
    - `destroy` (entity action)
  - new `PluginCapabilityGrants` entity set with actions:
    - `grant` (entity-set and tenant-scoped)
    - `revoke` (entity action)
  - action dispatch now enforces `required_capabilities` before handler
    execution.
  - `SandboxEnforcer.require(tenant_id, plugin_key, capability, context)`.
- Audit:
  - new `EvidenceBlobs` entity set with actions:
    - `register`
    - `verify_hash`
    - `place_legal_hold`
    - `release_legal_hold`
    - `redact`
    - `tombstone`
    - `purge`
- Ops Governance:
  - new `OpsRetentionClasses`, `OpsLegalHolds`, and
    `OpsLifecycleActionLogs`.
  - `OpsRetentionPolicies` extended with `run_lifecycle`.
  - `DataHandlingRecord` extended with optional `EvidenceBlobId`.

## Migration Summary

Single schema migration:
`a4f8c2d9e6b1_phase4_security_compliance_substrate`

- adds:
  - `mugen.admin_key_ref`
  - `mugen.admin_plugin_capability_grant`
  - `mugen.audit_evidence_blob`
  - `mugen.ops_governance_retention_class`
  - `mugen.ops_governance_legal_hold`
  - `mugen.ops_governance_lifecycle_action_log`
- extends:
  - `mugen.ops_governance_data_handling_record` with nullable
    `evidence_blob_id` + FK.
- includes:
  - tenant/purpose/key uniqueness and one-active-key partial unique index.
  - one-active-capability-grant partial unique index.
  - lifecycle log and evidence lookup indexes.
  - append-only lifecycle log trigger guard.
  - immutable evidence payload update guard trigger.

ACP reseed migration:
`aa6d5f4c3b2e_reseed_acp_for_phase4_security_compliance`

- re-applies manifests and seeds new resource/action permissions.

Follow-up guard migration:
`f1a9b7c3d5e2_ops_gov_retention_class_active_unique`

- validates no duplicate active retention classes already exist for a given
  `(tenant_id, resource_type)`.
- adds a partial unique index enforcing one active class per
  `(tenant_id, resource_type)`.

## Backward Compatibility

- Existing Phase 1-3 behavior remains valid.
- Existing config-backed audit hash key path still works as fallback when
  `KeyRef` resolution is unavailable.
- Existing `EvidenceRef` consumers continue to function unchanged.
- Audit hash-chain verification now resolves secrets by explicit `hash_key_id`
  via `KeyRefs` first (tenant, then global; statuses `active`/`retired`), then
  config fallback.
- Releasing an already-released legal hold now still re-syncs downstream target
  hold fields to repair partial-failure retries.
- Legal hold placement now enforces effective retention-class policy:
  `legal_hold_allowed=false` is a `409`, explicit class/resource mismatches are
  `409`, and ambiguous active-class state is `409`.

## Operational Rollout

1. Apply schema migration and ACP reseed migration.
2. Validate seeded actions/permissions for new entity sets.
3. Enable capability declarations for targeted actions.
4. Roll out evidence registration and legal hold orchestration paths.
5. Enable lifecycle runs (`dry_run` first, then execute) per tenant.

## Validation Expectations

- Capability denies for undeclared grants are auditable and deterministic.
- Audit hash-chain writes remain functional with `KeyRef` lookup + fallback.
- Evidence actions support register/verify/hold/redact/tombstone/purge flow.
- Legal holds block purge paths while active.
- Lifecycle runs (`dry_run` and execute) produce deterministic summaries and
  append-only lifecycle logs.
- Regression suites for Phase 1-3 continue passing unchanged.

## Out of Scope

- Cloud KMS provider implementations (AWS/GCP/Vault/HSM).
- OS/process-level sandboxing.
- Connector runtime work tracked in RFC-0014 (Phase 6).
- Downstream domain-specific retention executors.
