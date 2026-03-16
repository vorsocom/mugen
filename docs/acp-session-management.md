# ACP Session Management

Status: Draft  
Last Updated: 2026-02-24

## Scope

This document defines ACP backend session-token management behavior for refresh
token revocation.

## Revoke Refresh Token Action

Endpoint:

- `POST /core/acp/v1/RefreshTokens/{refresh_token_id}/$action/revoke`

Request body:

- empty object payload (`NoValidationSchema`)
- example:

```json
{}
```

Response contract:

- `204` when revoke succeeds
- `404` when the target refresh token does not exist
- `500` when a storage/database error occurs during revoke

Revoke semantics:

- revoke is implemented as hard delete of the refresh-token row
- no API version or route changes are introduced for this behavior

## Related Docs

- `docs/acp-rbac-policy.md`
- `docs/acp-role-permission-lifecycle.md`
