# Billing ACP Integration Boundary

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

`billing` is intentionally exposed through ACP generic CRUD/action endpoints,
not a separate billing-specific admin API layer. The contributor already
registers permissions, resources, service bindings, and actions in one place.
Downstream teams need a clear rule for extending billing without recreating ACP
abstractions.

## Decision

- Treat ACP as the admin control plane for billing resources and actions.
- Keep billing contributor logic in `mugen/core/plugin/billing/contrib.py` as
  the single registration surface for billing ACP resources.
- Keep billing API package (`mugen/core/plugin/billing/api`) reserved for
  non-ACP endpoints only.
- Keep plugin load order as `acp` before `billing` when enabling billing.

## Core vs Downstream Boundary

- Core responsibilities:
  - Provide generic ACP CRUD/action runtime, permissions, and seed manifests.
  - Register billing entity metadata, behavior, and action contracts.
  - Bind ACP resources to billing model/EDM/service implementations.
- Downstream responsibilities:
  - Configure tenant policy and seed values for production environments.
  - Add domain-specific non-ACP endpoints only when ACP actions are
    insufficient.
  - Operate plugin enablement order and rollout sequencing.
- Why this boundary:
  - Avoids duplicated transport/authorization/CRUD stacks.
  - Keeps billing plugin behavior consistent with ACP-owned semantics.

## Implementation Sketch

### Data Model

No downstream schema is required for this boundary. Billing model and migration
artifacts remain in the plugin and are surfaced through ACP resources.

### Services / APIs

1. Keep resource/action registration in `contrib.py`.
2. Use ACP CRUD/action endpoints for admin operations on billing entities.
3. Add billing-specific API routes only for use cases outside ACP semantics
   (for example external ingestion contracts).

### Operational Notes

- Enable `billing` only after `acp` in plugin ordering.
- Avoid parallel, custom admin endpoints that duplicate ACP CRUD/action paths.

## Validation

- Verify contributor registration creates expected ACP resources/actions.
- Verify permissions map to ACP verbs and billing objects.
- Verify no billing admin endpoint duplicates an ACP resource/action path.

## Risks / Open Questions

- Future billing features may pressure adding custom endpoints prematurely.
- Plugin load-order misconfiguration can cause missing ACP registration at boot.
