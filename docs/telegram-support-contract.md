# Telegram Support Contract

This document defines the v1 Telegram platform contract in muGen.

## Scope

- Ingress mode: webhook only.
- Webhook path: `POST /api/telegram/botapi/webhook/<path_token>`.
- Chat scope: private chats only (`chat.type == "private"`).
- Supported inbound update types:
  - `message`
  - `callback_query`
- Slash commands are treated as standard text input.
- Callback queries are always acknowledged first, then routed through text handling.

## Strict Startup Contract

When `"telegram"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid Telegram keys:
   - `telegram.bot.token`
   - `telegram.webhook.path_token`
   - `telegram.webhook.secret_token`
   - `telegram.webhook.dedupe_ttl_seconds`
   - `telegram.api.base_url`
   - `telegram.api.timeout_seconds`
   - `telegram.api.max_api_retries`
   - `telegram.api.retry_backoff_seconds`
   - `telegram.media.allowed_mimetypes`
   - `telegram.media.max_download_bytes`
   - `telegram.typing.enabled`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.telegram`
3. Required extension tokens are registered:
   - FW: `core.fw.telegram_botapi`
   - IPC: `core.ipc.telegram_botapi`

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. Telegram platform enabled gate.
2. Path token verification (`<path_token>` equals `telegram.webhook.path_token`).
3. Secret header verification (`X-Telegram-Bot-Api-Secret-Token` equals `telegram.webhook.secret_token`).

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Durable dedupe table: `telegram_botapi_event_dedup`.
- Durable dead-letter table: `telegram_botapi_event_dead_letter`.
- Duplicate message/callback events are ignored after first successful dedupe insert.
- Malformed payloads and unhandled processing failures are written to dead-letter persistence.

## Outbound Response Contract

- Generic response types remain supported:
  - `text`, `audio`, `file`, `image`, `video`
- Telegram-specific envelope is supported:
  - `{"type":"telegram","op":"send_message",...}`
  - `{"type":"telegram","op":"answer_callback",...}`

## Unsupported Boundaries (v1)

- Polling mode.
- Non-private chats (groups, channels, supergroups).
- Telegram-specific flows outside the envelope contract above.
