# WeChat Support Contract

This document defines the v1 WeChat platform contract in muGen.

## Scope

- Ingress mode: webhook only.
- Platform token: `wechat`.
- Tenant-aware ingress route resolution:
  [`channel-orchestration` downstream note](./downstream-notes/channel-orchestration.md#tenant-aware-ingress-routing).
- Providers in scope:
  - `official_account`
  - `wecom` (app messaging surface)
- One active provider per deployment selected by `wechat.provider`.
- Webhook routes:
  - Official Account: `GET/POST /api/wechat/official_account/webhook/<path_token>`
  - WeCom: `GET/POST /api/wechat/wecom/callback/<path_token>`

## Strict Startup Contract

When `"wechat"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid WeChat keys:
   - `wechat.provider`
   - `wechat.webhook.path_token`
   - `wechat.webhook.signature_token`
   - `wechat.webhook.aes_enabled`
   - `wechat.webhook.aes_key` (required when `aes_enabled=true`)
   - `wechat.webhook.dedupe_ttl_seconds`
   - `wechat.api.timeout_seconds`
   - `wechat.api.max_api_retries`
   - `wechat.api.retry_backoff_seconds`
   - `wechat.api.max_download_bytes`
   - `wechat.typing.enabled`
   - Provider branch keys:
     - `official_account`: `wechat.official_account.app_id`, `wechat.official_account.app_secret`
     - `wecom`: `wechat.wecom.corp_id`, `wechat.wecom.corp_secret`, `wechat.wecom.agent_id`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.wechat`
3. Required extension tokens are registered:
   - FW: `core.fw.wechat`
   - IPC: `core.ipc.wechat`

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WeChat platform enabled gate.
2. Path token verification (`<path_token>` equals `wechat.webhook.path_token`).
3. Active provider gate (official_account endpoint only when `provider=official_account`; wecom endpoint only when `provider=wecom`).
4. Signature verification:
   - Plain mode: SHA1 signature over sorted token/timestamp/nonce.
   - AES mode: SHA1 signature over sorted token/timestamp/nonce/encrypted-payload.

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Durable dedupe table: `wechat_event_dedup`.
- Durable dead-letter table: `wechat_event_dead_letter`.
- Duplicate webhook events are ignored after first successful dedupe insert.
- Malformed payloads and unhandled processing failures are written to dead-letter persistence.

## IPC Contract

- Official Account webhook dispatches `platform="wechat"`, `command="wechat_official_account_event"`.
- WeCom webhook dispatches `platform="wechat"`, `command="wechat_wecom_event"`.

## Outbound Response Contract

- Generic response types remain supported:
  - `text`, `audio`, `file`, `image`, `video`
- WeChat-specific envelope is supported:
  - `{"type":"wechat","op":"send_raw","content":{...}}`
  - `{"type":"wechat","op":"send_message","text":"..."}`

## Unsupported Boundaries (v1)

- WeCom customer-contact surfaces.
- Unofficial personal-account APIs.
- Curated first-class advanced provider message families beyond generic + raw passthrough.
