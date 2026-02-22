# ACP Tenant Invitations

Status: Draft  
Last Updated: 2026-02-22

## Scope

This document defines ACP tenant invitation delivery and redeem behavior.

## Configuration

Add these ACP settings:

- `acp.tenant_invitation_ttl_seconds`  
  Invitation token lifetime in seconds. Default: `604800` (7 days).
- `acp.tenant_invitation_invite_base_url`  
  Base URL used to build invite links included in outbound invitation emails.

## Delivery Policy

- Invitation `create` and `resend` require a configured `email_gateway`.
- If no email gateway is configured, API returns `503`.
- If the configured gateway fails to send, API returns `502`.
- Invitation email send happens before DB persist/update.
- Plaintext invitation token is never returned by ACP APIs.

## API Contracts

### Tenant lifecycle actions

- `POST /core/acp/v1/Tenants/{tenant_id}/$action/deactivate`
- `POST /core/acp/v1/Tenants/{tenant_id}/$action/reactivate`

Both require body:

```json
{ "RowVersion": 1 }
```

### Invitation lifecycle actions

- `POST /core/acp/v1/tenants/{tenant_id}/TenantInvitations/{invitation_id}/$action/resend`
  - Requires `{ "RowVersion": <int> }`
  - Returns `200` with invitation metadata only (no token)
- `POST /core/acp/v1/tenants/{tenant_id}/TenantInvitations/{invitation_id}/$action/revoke`
  - Requires `{ "RowVersion": <int> }`
  - Returns `204`

### Membership lifecycle actions

- `POST /core/acp/v1/tenants/{tenant_id}/TenantMemberships/{membership_id}/$action/suspend`
- `POST /core/acp/v1/tenants/{tenant_id}/TenantMemberships/{membership_id}/$action/unsuspend`
- `POST /core/acp/v1/tenants/{tenant_id}/TenantMemberships/{membership_id}/$action/remove`

All require:

```json
{ "RowVersion": 1 }
```

### Authenticated invitation redeem

- `POST /core/acp/v1/auth/tenants/{tenant_id}/invitations/{invitation_id}/redeem`
- Requires bearer auth (`global_auth_required`)
- Request body:

```json
{ "Token": "..." }
```

- Success response: `204`

## Error Semantics

- `400`: malformed payload/UUID.
- `403`: login email mismatch or invalid token.
- `404`: invitation/membership/tenant row not found.
- `409`: row-version mismatch, invalid status transition, replay, or expired token.
- `502`: outbound invitation send failed.
- `503`: invitation delivery unavailable (gateway/config missing).

## Status Transition Constraints

- Tenant status transitions are action-only:
  `active <-> suspended`.
- Tenant membership status transitions are action-only:
  `active <-> suspended`, plus `remove`.
- Tenant invitation:
  - `resend` allowed from `invited`/`expired` (terminal states conflict)
  - `revoke` allowed from `invited`
  - `redeem` allowed from `invited` with strict `login_email == invitation.email`.

PATCH writes to `Status` for `ACP.Tenant` and `ACP.TenantMembership` are rejected with `400`.
