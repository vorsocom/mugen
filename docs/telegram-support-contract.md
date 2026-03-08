# Telegram Support Contract

This document defines the current Telegram Bot API support contract in muGen.

## Scope

- Ingress mode: webhook only.
- Webhook path: `POST /api/telegram/botapi/webhook/<path_token>`.
- Multiple active Telegram client profiles may run concurrently in one
  deployment.
- Chat scope: private chats only.

## Configuration And ACP

When `telegram` is enabled in `mugen.platforms`, startup is fail-closed unless:

1. root config has valid process-level Telegram settings:
   - `telegram.webhook.dedupe_ttl_seconds`
   - `telegram.api.base_url`
   - `telegram.api.timeout_seconds`
   - `telegram.api.max_api_retries`
   - `telegram.api.retry_backoff_seconds`
   - `telegram.media.allowed_mimetypes`
   - `telegram.media.max_download_bytes`
   - `telegram.typing.enabled`
2. DI provider path resolves:
   - `mugen.modules.core.client.telegram`
3. required extension tokens are registered:
   - FW: `core.fw.telegram_botapi`
   - IPC: `core.ipc.telegram_botapi`

Telegram bot tokens, webhook path tokens, and webhook secret tokens are owned
by ACP `MessagingClientProfiles` plus `KeyRef` secrets. Zero active client
profiles is valid at startup.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. Telegram platform enabled gate.
2. Path token resolution through active ACP Telegram client profiles.
3. Secret header verification against the matched client profile secret.

Any verification failure is rejected before IPC dispatch.

## Webhook Registration

muGen does not call Telegram `setWebhook` automatically. Register each active
client profile with its ACP-owned `path_token` and secret token.

## Reliability Contract

- Each accepted Telegram logical update becomes one canonical ingress row with:
  - `platform="telegram"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="telegram_ingress_event"`
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- HTTP success is returned only after staging commits.
- IPC failures are retried by the shared worker and dead-lettered after the
  shared attempt budget.
