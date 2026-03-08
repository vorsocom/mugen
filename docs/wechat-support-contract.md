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
- One deployment may host multiple active WeChat runtime profiles, and provider
  selection is per runtime profile.
- Webhook routes:
  - Official Account: `GET/POST /api/wechat/official_account/webhook/<path_token>`
  - WeCom: `GET/POST /api/wechat/wecom/callback/<path_token>`

## Shared Ingress Foundation

WeChat transport ingress uses the shared durable ingress service described in
[Messaging Ingress Contract](./messaging-ingress-contract.md).

That means:

- provider/path/signature verification still happens at the HTTP edge;
- accepted webhook events are staged durably before business processing;
- webhook success acknowledges committed staging, not completed handler work.

## Strict Startup Contract

When `"wechat"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid WeChat keys:
   - shared root settings:
     - `wechat.webhook.dedupe_ttl_seconds`
     - `wechat.api.timeout_seconds`
     - `wechat.api.max_api_retries`
     - `wechat.api.retry_backoff_seconds`
     - `wechat.api.max_download_bytes`
     - `wechat.typing.enabled`
   - per-runtime-profile settings under `[[wechat.profiles]]`:
     - `key`
     - `provider`
     - `wechat.profiles[].webhook.path_token`
     - `wechat.profiles[].webhook.signature_token`
     - `wechat.profiles[].webhook.aes_enabled`
     - `wechat.profiles[].webhook.aes_key` (required when `aes_enabled=true`)
     - provider branch keys:
       - `official_account`: `wechat.profiles[].official_account.app_id`, `wechat.profiles[].official_account.app_secret`
       - `wecom`: `wechat.profiles[].wecom.corp_id`, `wechat.profiles[].wecom.corp_secret`, `wechat.profiles[].wecom.agent_id`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.wechat`
3. Required extension tokens are registered:
   - FW: `core.fw.wechat`
   - IPC: `core.ipc.wechat`

Legacy single-profile WeChat config is normalized to one implicit runtime
profile with key `default`.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WeChat platform enabled gate.
2. Path token verification (`<path_token>` resolves one configured
   `wechat.profiles[].webhook.path_token`).
3. Active provider gate (official_account endpoint only when the matched
   runtime profile has `provider=official_account`; wecom endpoint only when
   the matched runtime profile has `provider=wecom`).
4. Signature verification:
   - Plain mode: SHA1 signature over sorted token/timestamp/nonce using the
     matched runtime profile's signature token.
   - AES mode: SHA1 signature over sorted token/timestamp/nonce/encrypted-payload
     using the matched runtime profile's signature token and AES settings.

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Each accepted WeChat webhook event becomes one canonical ingress row with:
  - `platform="wechat"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="wechat_ingress_event"`
- Provider identity (`official_account` vs `wecom`) is preserved in
  `provider_context`.
- Shared reliability tables are:
  - `messaging_ingress_event`
  - `messaging_ingress_dedup`
  - `messaging_ingress_dead_letter`
- HTTP success is returned only after the staging transaction commits.
- Duplicate deliveries are absorbed by shared dedupe on
  `platform + runtime_profile_key + dedupe_key`.
- IPC/handler failures are retried by the shared worker and dead-lettered after
  the shared attempt budget.
- Older WeChat-specific reliability tables and the raw
  `wechat_official_account_event` / `wechat_wecom_event` ingress commands are
  not part of the current runtime contract.

## IPC Contract

- Shared ingress dispatches `platform="wechat"`, `command="wechat_ingress_event"`.
- The worker receives the canonical ingress envelope, not raw provider XML.

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
