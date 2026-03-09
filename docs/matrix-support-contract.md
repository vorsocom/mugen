# Matrix Support Contract

This document defines the current Matrix support boundary in muGen core.

## Intent

muGen keeps Matrix support DM-first and transport-account specific:

- stable assistant runtime for direct conversations,
- deterministic trust and media defaults,
- ACP-owned client accounts,
- no implicit global-tenant fallback.

## Shared Ingress Foundation

Matrix transport ingress uses the same durable ingress service as the webhook
platforms, even though the transport entrypoint is `/sync`.

## Configuration And ACP

When `matrix` is enabled in `mugen.platforms`, bootstrap is fail-closed unless:

1. root config has valid process-level Matrix settings:
   - `matrix.domains.allowed`
   - `matrix.domains.denied`
   - `matrix.invites.direct_only`
   - `matrix.media.allowed_mimetypes`
   - `matrix.media.max_download_bytes`
   - `matrix.security.device_trust.mode`
   - `security.secrets.encryption_key`
2. DI provider path resolves:
   - `mugen.modules.core.client.matrix`
3. required extension tokens are registered:
   - IPC: `core.ipc.matrix_ingress`

Homeserver URLs, Matrix users, device ids, and credentials are owned by ACP
`MessagingClientProfiles` plus `KeyRef` secrets. Zero active client profiles is
valid at startup.

Optional sender gating is also owned per `MessagingClientProfiles.settings`
using `user_access.mode` plus `user_access.users`.

Tenant-facing Matrix secrets should use ACP `KeyRef.provider = "managed"`.
Operator-local `provider = "local"` remains bootstrap / emergency only.

Matrix account display names are also owned by
`MessagingClientProfiles.display_name`, not root config.

## Device Verification Reads

- Global ACP administrators may read active runtime Matrix device verification
  data from `/core/acp/v1/runtime/matrix/device-verification-data`.
- Tenant owners and tenant admins may read their own tenant-owned active runtime
  Matrix device verification data from
  `/core/acp/v1/tenants/<tenant_id>/runtime/matrix/device-verification-data`.
- The tenant-scoped endpoint accepts optional `client_profile_id=<uuid>`
  filtering and fails closed when the requested runtime client profile is not
  owned by that tenant.
- These endpoints expose active runtime device state only; they do not read
  durable verification material from ACP rows.

## Message Routing Contract

- Ingress routing uses:
  - `channel_key = "matrix"`
  - `identifier_type = "recipient_user_id"`
  - `identifier_value = <active Matrix client profile user id>`
- Resolved bindings provide tenant-aware ingress metadata and `client_profile_id`
  to the messaging runtime.
- Missing, inactive, ambiguous, invalid, unauthorized, and resolver-error
  outcomes fail closed and drop inbound Matrix processing.
- There is no implicit global-tenant fallback.

`room_id` remains conversation context and reply destination metadata only.

## Checkpointing

- Accepted sync work is committed together with Matrix checkpoint updates.
- Matrix stores `checkpoint_key = "sync_token"` per `client_profile_id`.

## Reliability Contract

- Accepted room messages and supported callback payloads stage through the
  shared ingress tables.
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- IPC failures are retried by the shared worker and dead-lettered after the
  shared attempt budget.
