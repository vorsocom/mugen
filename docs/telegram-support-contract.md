# Telegram Support Contract

This document defines the v1 Telegram platform contract in muGen.

## Scope

- Ingress mode: webhook only.
- Webhook path: `POST /api/telegram/botapi/webhook/<path_token>`.
- One muGen runtime may host multiple active Telegram bot profiles
  concurrently.
- Tenant-aware ingress route resolution:
  [`channel-orchestration` downstream note](./downstream-notes/channel-orchestration.md#tenant-aware-ingress-routing).
- Chat scope: private chats only (`chat.type == "private"`).
- Supported inbound update types:
  - `message`
  - `callback_query`
- Slash commands are treated as standard text input.
- Callback queries are always acknowledged first, then routed through text handling.

## Shared Ingress Foundation

Telegram transport ingress uses the shared durable ingress service described in
[Messaging Ingress Contract](./messaging-ingress-contract.md).

That means:

- webhook verification still happens at the HTTP edge;
- accepted updates are staged durably before business processing;
- webhook success acknowledges committed staging, not completed handler work.

## Strict Startup Contract

When `"telegram"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid Telegram keys:
   - shared root settings:
     - `telegram.webhook.dedupe_ttl_seconds`
     - `telegram.api.base_url`
     - `telegram.api.timeout_seconds`
     - `telegram.api.max_api_retries`
     - `telegram.api.retry_backoff_seconds`
     - `telegram.media.allowed_mimetypes`
     - `telegram.media.max_download_bytes`
     - `telegram.typing.enabled`
   - per-runtime-profile settings under `[[telegram.profiles]]`:
     - `key`
     - `telegram.profiles[].bot.token`
     - `telegram.profiles[].webhook.path_token`
     - `telegram.profiles[].webhook.secret_token`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.telegram`
3. Required extension tokens are registered:
   - FW: `core.fw.telegram_botapi`
   - IPC: `core.ipc.telegram_botapi`

Legacy single-profile Telegram config is normalized to one implicit runtime
profile with key `default`.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. Telegram platform enabled gate.
2. Path token verification (`<path_token>` resolves one configured
   `telegram.profiles[].webhook.path_token`).
3. Secret header verification (`X-Telegram-Bot-Api-Secret-Token` equals the
   matched runtime profile's `webhook.secret_token`).

Any verification failure is rejected before IPC dispatch.

## Webhook Registration (Telegram-Side)

muGen does not automatically call Telegram `setWebhook`. Register each active
runtime profile explicitly.

`url` must use one of Telegram's allowed ports: `80`, `88`, `443`, or `8443`.

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "url=https://<your-domain>:8443/api/telegram/botapi/webhook/<path_token>" \
  --data-urlencode "secret_token=<secret_token>" \
  --data-urlencode "drop_pending_updates=false"
```

The `<path_token>` and `<secret_token>` values must match the same configured
runtime profile:

- `telegram.profiles[].webhook.path_token`
- `telegram.profiles[].webhook.secret_token`

Validate registration and delivery status:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

Remove webhook (for recovery/switching):

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook"
```

## Reliability Contract

- Each accepted Telegram logical update becomes one canonical ingress row with:
  - `platform="telegram"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="telegram_ingress_event"`
- `message` and `callback_query` updates are staged independently when present.
- Shared reliability tables are:
  - `messaging_ingress_event`
  - `messaging_ingress_dedup`
  - `messaging_ingress_dead_letter`
- HTTP success is returned only after the staging transaction commits.
- Duplicate deliveries are absorbed by shared dedupe on
  `platform + runtime_profile_key + dedupe_key`.
- IPC/handler failures are retried by the shared worker and dead-lettered after
  the shared attempt budget.
- Older Telegram-specific reliability tables and the raw
  `telegram_botapi_update` ingress command are not part of the current runtime
  contract.

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
