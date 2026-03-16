# ACP Role and Permission Lifecycle

Status: Draft  
Last Updated: 2026-02-24

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

## RBAC CRUD Mutability Boundaries

The RBAC CRUD surface is intentionally narrow to keep identity keys stable.

- `GlobalRoles`
  - create: `Namespace`, `Name`, `DisplayName`
  - patch: `DisplayName` only (`RowVersion` required)
  - `Namespace` / `Name` are immutable and PATCH attempts return `400`
- `Roles` (tenant-scoped)
  - create: `Namespace`, `Name`, `DisplayName` (`TenantId` is path-controlled)
  - patch: `DisplayName` only (`RowVersion` required)
  - `Namespace` / `Name` are immutable and PATCH attempts return `400`
- `PermissionObjects`
  - create: `Namespace`, `Name`
  - patch: disabled (`405`) to keep taxonomy keys immutable
- `PermissionTypes`
  - create: `Namespace`, `Name`
  - patch: disabled (`405`) to keep taxonomy keys immutable
- `GlobalPermissionEntries`
  - create: `GlobalRoleId`, `PermissionObjectId`, `PermissionTypeId`, `Permitted`
  - patch: `Permitted` only (`RowVersion` required)
  - role/object/type rebinding fields are immutable and PATCH attempts return `400`
- `PermissionEntries` (tenant-scoped)
  - create: `RoleId`, `PermissionObjectId`, `PermissionTypeId`, `Permitted`
    (`TenantId` is path-controlled)
  - patch: `Permitted` only (`RowVersion` required)
  - role/object/type rebinding fields are immutable and PATCH attempts return `400`

## Constraint Error Semantics

For RBAC create/update operations:

- malformed/invalid payload validation returns `400`
- DB unique conflicts return `409`
- DB FK/not-null/check/input-reference integrity violations return `400`

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
