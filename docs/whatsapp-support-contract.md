# WhatsApp Support Contract

This document defines the v1 WhatsApp Cloud API platform contract in muGen.

## Scope

- Ingress mode: webhook only.
- Webhook routes:
  - Subscription verification: `GET /api/whatsapp/wacapi/webhook`
  - Event delivery: `POST /api/whatsapp/wacapi/webhook`
- Supported inbound event families:
  - `messages` (`entry[].changes[].value.messages[]`)
  - `statuses` (`entry[].changes[].value.statuses[]`)
- Message handling coverage:
  - Direct AI routing: `text`, `interactive`, `button`, `audio`, `document`, `image`, `video`
  - Hook/fallback only: other message types

## Strict Startup Contract

When `"whatsapp"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid WhatsApp keys:
   - `whatsapp.app.secret`
   - `whatsapp.business.phone_number_id`
   - `whatsapp.graphapi.access_token`
   - `whatsapp.graphapi.base_url`
   - `whatsapp.graphapi.version`
   - `whatsapp.graphapi.timeout_seconds`
   - `whatsapp.graphapi.max_download_bytes`
   - `whatsapp.graphapi.typing_indicator_enabled`
   - `whatsapp.graphapi.max_api_retries` (optional; default `2`)
   - `whatsapp.graphapi.retry_backoff_seconds` (optional; default `0.5`)
   - `whatsapp.servers.verify_ip`
   - `whatsapp.servers.allowed` (required when `verify_ip=true`)
   - `whatsapp.servers.trust_forwarded_for`
   - `whatsapp.webhook.verification_token`
   - `whatsapp.webhook.dedupe_ttl_seconds`
   - `whatsapp.beta.users` (used when `mugen.beta.active=true`)
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.whatsapp`
3. Required extension tokens are registered:
   - FW: `core.fw.whatsapp_wacapi`
   - IPC: `core.ipc.whatsapp_wacapi`
4. Startup probe succeeds:
   - Graph API probe `GET /<phone_number_id>` against configured `graphapi.base_url` + `graphapi.version`.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WhatsApp platform enabled gate.
2. Optional server IP allow-list gate:
   - Enabled only when `whatsapp.servers.verify_ip=true`.
   - Request IP must match CIDR entries from file `config.basedir + whatsapp.servers.allowed`.
   - If `whatsapp.servers.trust_forwarded_for=true`, first `X-Forwarded-For` address is used.
3. Subscription verification (GET):
   - `hub.mode == "subscribe"`
   - `hub.verify_token == whatsapp.webhook.verification_token`
   - `hub.challenge` is required and echoed back.
4. Request signature verification (POST):
   - `X-Hub-Signature-256` header is required.
   - Signature must match `HMAC-SHA256(raw_body, whatsapp.app.secret)`.

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Durable dedupe table: `whatsapp_wacapi_event_dedup`.
- Durable dead-letter table: `whatsapp_wacapi_event_dead_letter`.
- Dedupe key is deterministic: `<event_type>:<sha256(normalized_payload)>`.
- Duplicate `message` and `status` events are ignored after first successful dedupe insert.
- Malformed webhook payloads and unhandled processing failures are written to dead-letter persistence.

## IPC Contract

- Webhook dispatches `platform="whatsapp"`, `command="whatsapp_wacapi_event"`.
- `value.messages[]` are processed as message events.
- `value.statuses[]` are processed as status events.

## Outbound Response Contract

- Generic response types remain supported:
  - `text`, `audio`, `file`, `image`, `video`
- WhatsApp-specific response types are supported:
  - `contacts`, `location`, `interactive`, `template`, `sticker`, `reaction`
- Media responses (`audio|file|image|video`) are uploaded first, then sent by Graph media id.
- Optional `reply_to` binds outbound replies to an inbound message context.
- Best-effort processing signals are supported through typing indicator requests when enabled.

## Unsupported Boundaries (v1)

- Polling mode.
- Non-Cloud WhatsApp providers.
- Automatic Meta webhook registration from muGen runtime.
- Full first-class coverage of all WhatsApp message families outside the contract above.
