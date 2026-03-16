# Signal Support Contract

This document defines the current Signal support contract in muGen.

## Scope

- Transport: `signal-cli-rest-api`.
- Ingress mode: websocket receive stream from `GET /v1/receive/{number}`.
- Multiple active Signal client profiles may run concurrently in one
  deployment.
- Supported inbound envelope types:
  - text messages
  - media attachments
  - reactions
  - receipts

## Configuration And ACP

When `signal` is enabled in `mugen.platforms`, startup is fail-closed unless:

1. root config has valid process-level Signal settings:
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
2. DI provider path resolves:
   - `mugen.modules.core.client.signal`
3. required extension tokens are registered:
   - IPC: `core.ipc.signal_restapi`

Signal account numbers, gateway base URLs, and bearer tokens are owned by ACP
`MessagingClientProfiles` plus `KeyRef` secrets. Zero active client profiles is
valid at startup.

At runtime, each active client profile must pass the Signal gateway health and
mode probes before it joins the live client map.

## Gateway Auth Contract

- Every Signal API request includes the matched client profile bearer token.
- Token-based authorization must be enforced by the gateway or proxy.

## Reliability Contract

- Each accepted Signal envelope becomes one canonical ingress row with:
  - `platform="signal"`
  - `source_mode="receive_loop"`
  - `identifier_type="account_number"`
  - `ipc_command="signal_ingress_event"`
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- Outbound reply dispatch stays pinned to the same `client_profile_id` that
  received the inbound event.
- IPC failures are retried by the shared worker and dead-lettered after the
  shared attempt budget.
