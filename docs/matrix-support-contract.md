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
