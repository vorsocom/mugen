# Matrix Support Contract

This document defines the current Matrix support boundary in muGen core.
It is a practical contract for contributors and downstream teams, not a
statement of full Matrix spec coverage.

## Intent

muGen core keeps Matrix support intentionally lean:

- provide a stable DM-oriented assistant runtime,
- enforce deterministic security and media handling defaults,
- expose extension hooks for non-core behavior instead of expanding
  core complexity.

## Supported In Core

### Session and Sync

- Matrix client login with stored-credential reuse.
- One muGen runtime may host multiple active Matrix runtime profiles
  concurrently.
- Sync lifecycle with bounded exponential backoff and jitter on transient
  failures.
- Explicit auth-failure shutdown path for token/auth errors.

### Invite and Room Gating

- Domain allow/deny checks for incoming invites.
- Optional beta-user gating.
- Direct-message invite gating (`matrix.invites.direct_only`).
- Invite acceptance is not gated by ingress-route bindings.
- Room direct-flag check before processing inbound user messages.

### Runtime Configuration Contract (Matrix Enabled)

When `matrix` is enabled in `mugen.platforms`, bootstrap is strict fail-closed.

Shared required root settings:

- `matrix.domains.allowed` (non-empty `list[str]`)
- `matrix.domains.denied` (`list[str]`)
- `matrix.invites.direct_only` (`bool`)
- `matrix.media.allowed_mimetypes` (non-empty `list[str]`)
- `matrix.media.max_download_bytes` (positive integer)
- `matrix.security.device_trust.mode` (`strict_known|allowlist|permissive`)
- if mode is `allowlist`, every entry must include non-empty `user_id` and
  non-empty `device_ids`
- `security.secrets.encryption_key` (non-empty string)

Per-runtime-profile required settings under `[[matrix.profiles]]`:

- `key` (non-empty unique string)
- `homeserver` (non-empty string)
- `client.user` (non-empty string)
- `client.password` (non-empty string)

Legacy single-profile Matrix config is normalized to one implicit runtime
profile with key `default`.

Legacy permissive fallback behavior for malformed matrix runtime policy is not
supported.

### Device Trust

- Policy-driven trust modes:
  - `strict_known`
  - `allowlist`
  - `permissive`
- Deterministic handling of unknown/untrusted devices per mode.

### Message Handling

- Tenant-aware ingress routing for inbound room messages using
  `IngressBindings` with:
  - `channel_key = "matrix"`
  - `identifier_type = "recipient_user_id"`
  - `identifier_value = <active Matrix runtime profile user id>`
- Resolved bindings provide tenant-aware `ContextScope` and ingress metadata to
  the messaging runtime.
- Missing binding or missing recipient identifier falls back to the global
  tenant.
- Inactive, ambiguous, invalid, unauthorized, and resolver-error outcomes fail
  closed and drop inbound Matrix message processing before messaging handlers
  run.
- `room_id` remains conversation context and reply destination metadata; it is
  not the tenant-routing identifier.
- Text messages (`m.text`) routed into messaging service handlers.
- Encrypted media handling for audio/file/image/video:
  - MIME allowlist enforcement,
  - declared/downloaded size checks,
  - decryption failure handling,
  - temporary file cleanup after processing.

### Extension Hooks

- Non-core Matrix callbacks are enqueued to a bounded in-memory IPC dispatch
  queue and forwarded asynchronously to IPC extensions via the `matrix_event`
  command.
- The callback hot path is non-blocking: callback handlers enqueue and return
  without awaiting IPC extension execution.
- Inline fallback dispatch is not supported in callback handlers. When enqueue
  cannot be accepted, core drops the event and emits operator-visible warning
  logs.
- Queue overflow policy is `drop-new` with warning log emission and an
  incremented `matrix.ipc.dispatch.queue_full_drop_new` counter.
- `matrix_event` payloads include `version=1` plus `callback`, `event_type`,
  `reason`, optional `room_id`, and available `content`/`source` fields.
- Core skip logging remains reason-coded even when extensions are not present.

### IPC Failure Semantics

- Non-critical IPC handler failures are fail-open:
  - Matrix callback flow continues.
  - aggregate errors are logged as warnings and tracked via
    `matrix.ipc.dispatch.non_critical_failure*` metrics.
- Critical IPC handler failures are fail-closed:
  - core IPC raises `IPCCriticalDispatchError`,
  - Matrix runtime health monitor surfaces that failure to orchestration,
  - phase-B supervision degrades and restarts the Matrix runtime path.

### Observability

- Structured decision logs for invite/message/media branches with
  `domain`, `action`, and `reason`.
- In-memory counters keyed as:
  - `matrix.<domain>.<action>.<reason>`

## Intentionally Unsupported In Core

The following are currently outside muGen core scope and should be implemented
downstream via extensions where needed:

- Full Matrix feature parity (threads, reactions, edits, redactions, rich event
  workflows).
- Group-room assistant orchestration beyond DM-first behavior.
- Persistent metrics export/storage backend (Prometheus/OpenTelemetry/etc.).
- Business-policy-specific moderation/escalation logic for Matrix events.
- Automated handling flows for non-core to-device/state events beyond the
  extension-forwarding contract.

## Change Policy

If Matrix behavior is changed in core, update this contract in the same PR and
include tests covering:

- supported behavior changes,
- unsupported-boundary changes,
- extension contract compatibility (when payload shape changes).
