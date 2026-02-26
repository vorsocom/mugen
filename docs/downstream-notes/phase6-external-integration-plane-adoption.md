# Phase 6 External Integration Plane Adoption

- Status: draft
- Owner: platform-core
- Last Updated: 2026-02-26

## Context

Phase 6 introduces a new plugin, `ops_connector`, to standardize external HTTP
connector execution behind ACP-managed resources and action flows. This phase
adds schema-backed type registries, tenant runtime instances, immutable call
logs, and inline SLA escalation on connector failures.

## Locked Decisions

- Plugin namespace: `com.vorsocomputing.mugen.ops_connector`.
- Runtime adapter scope for this phase: `http_json` only.
- Failure escalation path: inline `ops_sla` execute action.
- Connector type registry remains DB-backed (`OpsConnectorTypes`).
- Persisted request/response payloads are redacted and hash-addressed.

## Core Surface Changes

- New entity sets:
  - `OpsConnectorTypes` (`OPSCONNECTOR.ConnectorType`)
  - `OpsConnectorInstances` (`OPSCONNECTOR.ConnectorInstance`)
  - `OpsConnectorCallLogs` (`OPSCONNECTOR.ConnectorCallLog`)
- New tenant entity actions on `OpsConnectorInstances`:
  - `test_connection`
  - `invoke`
- Required action capabilities:
  - `connector:invoke`
  - `net:outbound`
  - `secrets:read`

## Runtime Behavior

- `invoke`:
  - resolves active connector instance/type/capability
  - validates input/output payloads via ACP schema registry references
  - resolves secret material from ACP `KeyRefs`
  - executes outbound HTTP with retry/backoff and timeout policy precedence
  - writes immutable call log rows with redacted payload + deterministic hashes
  - optionally performs dedup replay via ACP dedup ledger when `ClientActionKey`
    is provided
  - invokes `OpsSlaEscalationPolicies/$action/execute` inline on failure when
    `EscalationPolicyKey` is configured
  - emits business-trace events for action start/success/error
- `test_connection`:
  - executes health probe (`ConfigJson.HealthPath`, default `/`)
  - writes immutable call log row (`CapabilityName=__test_connection__`)
  - always returns a `200` envelope with success/failure diagnostics

## Migration Summary

Schema migration:
`d9f2a4b6c8e0_phase6_ops_connector_schema`

- creates enums:
  - `ops_connector_instance_status` (`active|disabled|error`)
  - `ops_connector_call_log_status` (`ok|retrying|failed`)
- creates tables:
  - `mugen.ops_connector_type`
  - `mugen.ops_connector_instance`
  - `mugen.ops_connector_call_log`
- adds indexes for tenant/status/type/trace timelines
- adds trigger guards preventing `UPDATE`/`DELETE` on call log rows

ACP reseed migration:
`e3b5d7f9a1c2_reseed_acp_for_phase6_ops_connector`

- re-applies manifest registration for new resources/actions/permissions.

## Rollout Notes

1. Apply schema migration.
2. Apply ACP reseed migration.
3. Verify `KeyRefs` purpose `ops_connector_secret` is available for each tenant
   or globally.
4. Onboard connector types and tenant instances.
5. Enable `invoke` traffic tenant-by-tenant while monitoring failure/escalation
   rates and call-log growth.

## Out of Scope

- Non-`http_json` connector runtimes.
- External event-bus emission for connector failures.
- Async worker dispatch for connector invocation lifecycle.
