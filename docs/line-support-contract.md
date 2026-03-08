# LINE Support Contract

This document defines the v1 LINE Messaging API platform contract in muGen.

## Scope

- Ingress mode: webhook only.
- Webhook path: `POST /api/line/messagingapi/webhook/<path_token>`.
- One muGen runtime may host multiple active LINE runtime profiles
  concurrently.
- Tenant-aware ingress route resolution:
  [`channel-orchestration` downstream note](./downstream-notes/channel-orchestration.md#tenant-aware-ingress-routing).
- Chat scope: user 1:1 events only (`source.type == "user"`).
- Supported inbound event families:
  - Direct AI routing: `message`, `postback`
- Hook-only lifecycle: `follow`, `unfollow`, `accountLink`, `beacon`
- Group and room events are ignored in v1.

## Shared Ingress Foundation

LINE transport ingress uses the shared durable ingress service described in
[Messaging Ingress Contract](./messaging-ingress-contract.md).

That means:

- webhook verification still happens at the HTTP edge;
- accepted events are durably staged before business processing;
- webhook success acknowledges committed staging, not completed handler work.

## Strict Startup Contract

When `"line"` is enabled in `mugen.platforms`, startup is fail-closed unless all requirements below are met:

1. Runtime config has valid LINE keys:
   - shared root settings:
     - `line.webhook.dedupe_ttl_seconds`
     - `line.api.base_url`
     - `line.api.timeout_seconds`
     - `line.api.max_api_retries`
     - `line.api.retry_backoff_seconds`
     - `line.media.allowed_mimetypes`
     - `line.media.max_download_bytes`
     - `line.typing.enabled`
   - per-runtime-profile settings under `[[line.profiles]]`:
     - `key`
     - `line.profiles[].channel.access_token`
     - `line.profiles[].channel.secret`
     - `line.profiles[].webhook.path_token`
2. DI provider path exists and resolves:
   - `mugen.modules.core.client.line`
3. Required extension tokens are registered:
   - FW: `core.fw.line_messagingapi`
   - IPC: `core.ipc.line_messagingapi`

Legacy single-profile LINE config is normalized to one implicit runtime profile
with key `default`.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. LINE platform enabled gate.
2. Path token verification (`<path_token>` resolves one configured
   `line.profiles[].webhook.path_token`).
3. Signature verification (`X-Line-Signature`) using HMAC-SHA256 over raw body
   with the matched runtime profile's `channel.secret`, base64 encoded.

Any verification failure is rejected before IPC dispatch.

## Reliability Contract

- Each accepted LINE event becomes one canonical ingress row with:
  - `platform="line"`
  - `source_mode="webhook"`
  - `identifier_type="path_token"`
  - `ipc_command="line_ingress_event"`
- Shared reliability tables are:
  - `messaging_ingress_event`
  - `messaging_ingress_dedup`
  - `messaging_ingress_dead_letter`
- HTTP success is returned only after the staging transaction commits.
- Duplicate deliveries are absorbed by shared dedupe on
  `platform + runtime_profile_key + dedupe_key`.
- IPC/handler failures are retried by the shared worker and dead-lettered after
  the shared attempt budget.
- Older LINE-specific reliability tables and the raw
  `line_messagingapi_event` ingress command are not part of the current runtime
  contract.

## Outbound Response Contract

- Generic response types remain supported:
  - `text`, `audio`, `file`, `image`, `video`
- LINE-specific envelope is supported:
  - `{"type":"line","op":"reply",...}`
  - `{"type":"line","op":"push",...}`
  - `{"type":"line","op":"multicast",...}`
- Reply-token handling batches outbound messages and falls back to push when reply delivery is unavailable.

## Media Egress Contract

- Outbound media payloads must use `https://` URLs.
- Non-HTTPS local or unsupported payloads are rejected/logged and do not crash IPC flow.

## Unsupported Boundaries (v1)

- LIFF, rich menu management, and non-messaging management APIs.
- Group/room chat routing.
- Automatic media publishing pipeline for local files.
