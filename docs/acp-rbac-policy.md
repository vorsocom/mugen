# ACP RBAC Policy

Status: Draft  
Last Updated: 2026-09-05

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
- the tenant is missing, inactive, or deleted
- the tenant membership is missing or inactive, unless the user holds
  the recognized global administrator role

Tenant and membership eligibility is a prerequisite for tenant-scoped access,
including access granted through global roles. A suspended membership cannot
retain tenant access through an existing tenant role or global grant. Membership
in another tenant does not satisfy this prerequisite.

The recognized global administrator role is `administrator` in the configured ACP
namespace. Global administrators may administer active tenants without an active
membership in each tenant. This exception also applies when
`allow_global_admin=False`; that flag controls permission-grant override only.
Global administrators cannot bypass a missing, inactive, or deleted tenant.
Suspending a global administrator's tenant membership does not revoke their global
authority; remove the global administrator role to revoke that authority.
Disabling the account prevents new authenticated requests.

## Evaluation Order and Precedence

Authorization evaluation order is:

1. Resolve permission object/type identities.
2. For tenant-scoped requests, require an active, undeleted tenant and an active
   membership, subject to the global administrator membership exception.
3. Optionally apply the global administrator grant override when enabled by caller.
4. Evaluate global-role grants.
5. Evaluate tenant-role grants (when tenant context is present and needed).

Precedence rules:

- explicit deny takes precedence over allow within each evaluation stage
- a matching global allow returns success before tenant-grant evaluation, after
  tenant and membership eligibility have passed
- missing grants after evaluation results in deny

With `allow_global_admin=False`, global administrators follow the normal grant
evaluation and explicit-deny rules. With `allow_global_admin=True`, recognized
global administrators bypass grant evaluation after eligibility checks succeed.
Global authorization without a tenant context retains its existing grant rules
and does not require tenant membership.

## Endpoint Guard Behavior

`permission_required` performs guard checks before RBAC evaluation:

- unknown entity set -> `404`
- operation/action not allowed by resource capabilities -> `405`
- missing/invalid required tenant path parameter -> `400`
- RBAC deny result -> `403`

The guard always validates the tenant path and calls `IAuthorizationService`,
including for global administrators with grant override enabled. Administrator-only
actions still require the global administrator role in addition to the shared
authorization checks.

`global_auth_required` and `global_admin_required` are separate authn/authz
decorators and do not replace RBAC checks on endpoints using
`permission_required`.

## Revocation and Long-Lived Responses

Tenant state, membership state, and authorization decisions are read afresh for
each authorization check. Cached permission object/type identities do not cache
eligibility or grants. After suspension, the next tenant permission check denies
access without requiring the user's authentication token to expire. Membership
and grants for unrelated active tenants remain independently evaluated.

Tenant human-handoff SSE responses recheck permission before emitting each replay,
live event, or keepalive chunk. Revocation closes the response and its underlying
iterator. An idle response closes when its next keepalive is produced (every 15
seconds). Web SSE rechecks the authenticated owner and persisted conversation
tenant before opening the stream and before each chunk. Tenant conversations
require permission in that tenant; access to another tenant cannot keep a revoked
conversation stream open. Conversations in the global scope retain the existing
any-eligible-tenant web access rules. Web keepalive intervals are configurable and
default to 15 seconds. Revocation cannot retract data already sent before the
state change.

## Bootstrap Grants

ACP core seeds baseline global grants during registry contribution:

- `administrator`: broad read/create/update/delete/manage over ACP-owned objects
- `authenticated`: read/manage grant on the `user` permission object

These are explicit bootstrap grants, not exceptions to deny-by-default.

## Related Docs

- `docs/services.md`
- `docs/acp-role-permission-lifecycle.md`
- `docs/acp-tenant-invitations.md`
