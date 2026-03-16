# LINE Support Contract

This document defines the current LINE Messaging API support contract in
muGen.

## Scope

- Ingress mode: webhook only.
- Webhook path: `POST /api/line/messagingapi/webhook/<path_token>`.
- Multiple active LINE client profiles may run concurrently in one deployment.
- Chat scope: user 1:1 events only.

## Configuration And ACP

When `line` is enabled in `mugen.platforms`, startup is fail-closed unless:

1. root config has valid process-level LINE settings:
   - `line.webhook.dedupe_ttl_seconds`
   - `line.api.base_url`
   - `line.api.timeout_seconds`
   - `line.api.max_api_retries`
   - `line.api.retry_backoff_seconds`
   - `line.media.allowed_mimetypes`
   - `line.media.max_download_bytes`
   - `line.typing.enabled`
2. DI provider path resolves:
   - `mugen.modules.core.client.line`
3. required extension tokens are registered:
   - FW: `core.fw.line_messagingapi`
   - IPC: `core.ipc.line_messagingapi`

Active LINE accounts, webhook path tokens, and secrets are owned by ACP
`MessagingClientProfiles` plus `KeyRef` secrets. Zero active client profiles is
valid at startup.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. LINE platform enabled gate.
2. Path token resolution through active ACP LINE client profiles.
3. Signature verification using the matched client profile secret.

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Each accepted LINE event becomes one canonical ingress row with:
  - `platform="line"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="line_ingress_event"`
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- HTTP success is returned only after staging commits.
- IPC failures are retried by the shared worker and dead-lettered after the
  shared attempt budget.
