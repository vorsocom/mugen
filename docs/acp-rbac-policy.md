# ACP RBAC Policy

Status: Draft  
Last Updated: 2026-02-23

## Scope

This document defines authorization policy for ACP HTTP surfaces that use
`permission_required` and `IAuthorizationService`.

## Policy Model

ACP authorization is role-based and grant-driven:

- permission object: namespaced resource identity (`namespace:name`)
- permission type: namespaced action verb (`namespace:name`)
- grants:
  - global grants (`ACP.GlobalPermissionEntry`) attached to global roles
  - tenant grants (`ACP.PermissionEntry`) attached to tenant roles
- grant value:
  - `permitted = true` means allow
  - `permitted = false` means explicit deny

## Default Stance

ACP authorization is deny-by-default.

Access is denied when any of the following are true:

- permission object/type key is invalid
- permission object/type cannot be resolved
- no matching allow grant is found
- no tenant context exists for tenant-scoped authorization

## Evaluation Order and Precedence

Authorization evaluation order is:

1. Resolve permission object/type identities.
2. Optionally apply global admin bypass when enabled by caller.
3. Evaluate global-role grants.
4. Evaluate tenant-role grants (when tenant context is present and needed).

Precedence rules:

- explicit deny takes precedence over allow within each evaluation stage
- a matching global allow returns success before tenant-stage evaluation
- missing grants after evaluation results in deny

## Endpoint Guard Behavior

`permission_required` performs guard checks before RBAC evaluation:

- unknown entity set -> `404`
- operation/action not allowed by resource capabilities -> `405`
- missing/invalid required tenant path parameter -> `400`
- RBAC deny result -> `403`

`global_auth_required` and `global_admin_required` are separate authn/authz
decorators and do not replace RBAC checks on endpoints using
`permission_required`.

## Bootstrap Grants

ACP core seeds baseline global grants during registry contribution:

- `administrator`: broad read/create/update/delete/manage over ACP-owned objects
- `authenticated`: read/manage grant on the `user` permission object

These are explicit bootstrap grants, not exceptions to deny-by-default.

## Related Docs

- `docs/services.md`
- `docs/acp-role-permission-lifecycle.md`
- `docs/acp-tenant-invitations.md`
