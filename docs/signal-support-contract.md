# Signal Support Contract

This document defines the v1 Signal platform contract in muGen.

## Scope

- Transport: `signal-cli-rest-api` HTTP gateway.
- Ingress mode: websocket receive stream from `GET /v1/receive/{number}`.
- Tenant-aware ingress route resolution:
  [`channel-orchestration` downstream note](./downstream-notes/channel-orchestration.md#tenant-aware-ingress-routing).
- Account model: multiple Signal accounts may run concurrently in one deployment
  via `signal.profiles[]`.
- Supported inbound envelope types:
  - text messages
  - media attachments
  - reactions
  - receipt envelopes (observed/logged)
- No muGen webhook endpoint is exposed for Signal in v1.

## Strict Startup Contract

When `"signal"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid Signal keys:
   - shared root settings:
     - `signal.api.timeout_seconds`
     - `signal.api.max_api_retries`
     - `signal.api.retry_backoff_seconds`
     - `signal.receive.heartbeat_seconds`
     - `signal.receive.reconnect_base_seconds`
     - `signal.receive.reconnect_max_seconds`
     - `signal.receive.reconnect_jitter_seconds`
     - `signal.receive.dedupe_ttl_seconds`
     - `signal.media.allowed_mimetypes`
     - `signal.media.max_download_bytes`
     - `signal.typing.enabled`
   - per-runtime-profile settings under `[[signal.profiles]]`:
     - `key`
     - `signal.profiles[].account.number`
     - `signal.profiles[].api.base_url`
     - `signal.profiles[].api.bearer_token`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.signal`
3. Required extension tokens are registered:
   - IPC: `core.ipc.signal_restapi`

Legacy single-profile Signal config is normalized to one implicit runtime
profile with key `default`.

At runtime, client startup verifies:

1. each configured runtime profile passes `GET /v1/health`;
2. each configured runtime profile returns mode `json-rpc` from `GET /v1/about`.

## Gateway Auth Contract

- Every Signal API request includes `Authorization: Bearer <matched runtime profile bearer token>`.
- Token-based authorization must be enforced by the gateway/proxy.

## Reliability Contract

- Durable dedupe table: `signal_restapi_event_dedup`.
- Durable dead-letter table: `signal_restapi_event_dead_letter`.
- Dedupe key format: `<event_type>:<sha256(normalized_payload)>`.
- Malformed payloads and unhandled processing failures are written to dead-letter persistence.
- One receive loop runs per active runtime profile and inbound events retain the
  resolved `runtime_profile_key` for outbound reply dispatch.

## Outbound Response Contract

- Generic response types are supported:
  - `text`, `audio`, `file`, `image`, `video`
- Signal-specific envelope ops are supported:
  - `{"type":"signal","op":"send_message",...}`
  - `{"type":"signal","op":"send_reaction",...}`
  - `{"type":"signal","op":"send_receipt",...}`

## Unsupported Boundaries (v1)

- Signal account provisioning/registration/linking lifecycle.
- Stories, polls, stickers, calls.
- Full Signal group administration features.
