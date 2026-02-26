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
- Sync lifecycle with bounded exponential backoff and jitter on transient
  failures.
- Explicit auth-failure shutdown path for token/auth errors.

### Invite and Room Gating

- Domain allow/deny checks for incoming invites.
- Optional beta-user gating.
- Direct-message invite gating (`matrix.invites.direct_only`).
- Room direct-flag check before processing inbound user messages.

### Device Trust

- Policy-driven trust modes:
  - `strict_known`
  - `allowlist`
  - `permissive`
- Deterministic handling of unknown/untrusted devices per mode.

### Message Handling

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
- Queue overflow policy is `drop-new` with warning log emission and an
  incremented `matrix.ipc.dispatch.queue_full_drop_new` counter.
- `matrix_event` payloads include `version=1` plus `callback`, `event_type`,
  `reason`, optional `room_id`, and available `content`/`source` fields.
- Core skip logging remains reason-coded even when extensions are not present.

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
