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

## Shared Ingress Foundation

Matrix transport ingress uses the shared durable ingress service described in
[Messaging Ingress Contract](./messaging-ingress-contract.md).

Unlike webhook platforms, Matrix transport still enters through `/sync`, but
accepted inbound events now follow the same durable staging and worker model as
the other external messaging platforms.

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
- Accepted room messages are normalized into canonical ingress rows and staged
  before messaging handlers run.
- Text messages (`m.text`) are processed through the shared ingress worker.
- Encrypted media handling for audio/file/image/video:
  - MIME allowlist enforcement,
  - declared/downloaded size checks,
  - decryption failure handling,
  - temporary file cleanup after processing.

### Checkpointing

- Accepted sync work is committed together with Matrix sync checkpoint updates.
- Shared checkpoint table: `messaging_ingress_checkpoint`.
- Matrix stores `checkpoint_key = "sync_token"` per `runtime_profile_key`.
- The old direct sync-token persistence path is no longer the primary runtime
  contract.

### Extension Hooks

- Built-in durable Matrix ingress processing expects IPC extension token
  `core.ipc.matrix_ingress`.
- Accepted room messages are staged with:
  - `platform="matrix"`
  - `source_mode="sync_room_message"`
  - `identifier_type="recipient_user_id"`
  - `ipc_command="matrix_ingress_event"`
- Accepted non-core Matrix callbacks are also staged, using
  `source_mode="sync_callback"` and the same normalized
  `matrix_ingress_event` command.
- Canonical Matrix ingress payloads include the shared ingress envelope plus:
  - room-message payloads with normalized Matrix event data and ingress route
    metadata;
  - non-core callback payloads carrying callback name, event type, reason, and
    available content/source metadata.
- The old bounded in-memory `matrix_event` runtime contract is no longer the
  current public ingress contract.

### Worker Adapter Contract

The Matrix client remains responsible for worker-owned Matrix behaviors:

- emitting best-effort processing/typing signals;
- downloading and decrypting inbound media from canonical ingress payloads;
- sending normalized response payloads back to Matrix rooms;
- processing canonical `matrix_ingress_event` rows.

### IPC Failure Semantics

- Shared ingress worker failures are transport-fail-open but row-fail-closed:
  - `/sync` callback flow continues after staging;
  - IPC aggregate errors and exceptions mark the row failed for retry;
  - rows are requeued until the shared attempt budget is exhausted;
  - terminal failures are copied to `messaging_ingress_dead_letter`.

### Observability

- Structured decision logs for invite/message/media branches with
  `domain`, `action`, and `reason`.
- In-memory counters keyed as:
  - `matrix.<domain>.<action>.<reason>`
- Durable operator visibility for staged, completed, failed, and dead-lettered
  Matrix ingress rows is provided by the shared ingress tables.

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
- Native webhook ingress for Matrix transport.

## Change Policy

If Matrix behavior is changed in core, update this contract in the same PR and
include tests covering:

- supported behavior changes,
- unsupported-boundary changes,
- extension contract compatibility (when payload shape changes).
