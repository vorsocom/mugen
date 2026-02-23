# ACP Role and Permission Lifecycle

Status: Draft  
Last Updated: 2026-02-23

## Scope

This document defines lifecycle behavior for:

- tenant-scoped roles (`ACP.Role`)
- core permission taxonomy entities:
  - permission objects (`ACP.PermissionObject`)
  - permission types (`ACP.PermissionType`)

For RBAC authorization policy semantics (including deny-by-default), see
`docs/acp-rbac-policy.md`.

## Lifecycle Endpoints

All lifecycle actions require:

```json
{ "RowVersion": 1 }
```

### Role lifecycle (tenant-scoped)

- `POST /core/acp/v1/tenants/{tenant_id}/Roles/{role_id}/$action/deprecate`
- `POST /core/acp/v1/tenants/{tenant_id}/Roles/{role_id}/$action/reactivate`

### Permission taxonomy lifecycle (non-tenant)

- `POST /core/acp/v1/PermissionObjects/{permission_object_id}/$action/deprecate`
- `POST /core/acp/v1/PermissionObjects/{permission_object_id}/$action/reactivate`
- `POST /core/acp/v1/PermissionTypes/{permission_type_id}/$action/deprecate`
- `POST /core/acp/v1/PermissionTypes/{permission_type_id}/$action/reactivate`

## Transition Rules

- Allowed transitions:
  - `active -> deprecated`
  - `deprecated -> active`
- Invalid transition state returns `409`.
- Row-version conflict returns `409`.
- Missing target row returns `404`.
- Successful transition returns `204`.

## Action-Only Status Management

Direct PATCH writes to `Status` are rejected with `400` for:

- `ACP.Role`
- `ACP.PermissionObject`
- `ACP.PermissionType`

Use lifecycle actions instead.

## Core Taxonomy Delete Policy

Core permission taxonomy is lifecycle-managed and not hard-deleted.

- `PermissionObject` hard delete is disabled.
- `PermissionType` hard delete is disabled.
- Deprecation/reactivation actions are the supported lifecycle mechanism.

This preserves stable identifiers for grants, policy evaluation, and historical
auditability.

## Tenant Role-Template Provisioning Boundary

Tenant role-template provisioning belongs to downstream applications where
business process semantics live.

- ACP core provides registry/migration primitives for templates and grants.
- Downstream applications define template manifests and rollout timing.
- ACP core does not hardcode app-specific tenant role templates.
