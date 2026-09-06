# WeChat Support Contract

This document defines the current WeChat support contract in muGen.

## Scope

- Ingress mode: webhook only.
- Providers in scope:
  - `official_account`
  - `wecom`
- Webhook routes:
  - `GET/POST /api/wechat/official_account/webhook/<path_token>`
  - `GET/POST /api/wechat/wecom/callback/<path_token>`
- Multiple active WeChat client profiles may run concurrently in one
  deployment.

## Configuration And ACP

When `wechat` is enabled in `mugen.platforms`, startup is fail-closed unless:

1. root config has valid process-level WeChat settings:
   - `wechat.webhook.dedupe_ttl_seconds`
   - `wechat.api.timeout_seconds`
   - `wechat.api.max_api_retries`
   - `wechat.api.retry_backoff_seconds`
   - `wechat.api.max_download_bytes`
   - `wechat.typing.enabled`
2. DI provider path resolves:
   - `mugen.modules.core.client.wechat`
3. required extension tokens are registered:
   - FW: `core.fw.wechat`
   - IPC: `core.ipc.wechat`

Provider selection, webhook path tokens, signature material, and provider app
credentials are owned by ACP `MessagingClientProfiles` plus `KeyRef` secrets.
Zero active client profiles is valid at startup.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WeChat platform enabled gate.
2. Path token resolution through active ACP WeChat client profiles.
3. Provider gate:
   - official-account endpoint accepts only `provider=official_account`
   - wecom endpoint accepts only `provider=wecom`
4. Event signature verification over the encrypted body using the matched
   client profile secret material.
5. Event timestamps within 300 seconds of server time, in either direction.

Any verification failure is rejected before IPC dispatch.

POST events require an `Encrypt` envelope and `msg_signature`. Plaintext POST
events are rejected even when the profile has `webhook.aes_enabled=false`,
because plaintext signatures do not authenticate the message body. Configure
encrypted callbacks at the provider and set the ACP messaging client profile's
`webhook.aes_enabled=true` and `webhook.aes_key` secret reference. GET subscription
verification continues to follow the profile's selected mode. Keep the server
clock synchronized; delivery retries inside the timestamp window remain subject
to the existing event deduplication.

Media downloads enforce `wechat.api.max_download_bytes` while reading the
response stream, including responses without a trustworthy `Content-Length`.
An oversized declared response is rejected before reading its body; otherwise
reading stops after at most one byte beyond the limit without writing a file.

## Reliability Contract

- Each accepted WeChat webhook event becomes one canonical ingress row with:
  - `platform="wechat"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="wechat_ingress_event"`
- Provider identity is preserved in `provider_context`.
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- HTTP success is returned only after staging commits.
