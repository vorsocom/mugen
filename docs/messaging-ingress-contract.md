# Messaging Ingress Contract

This document defines the shared durable ingress contract for external messaging
platforms in muGen core.

## Scope

The shared ingress foundation applies to:

- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

The `web` platform is explicitly out of scope and keeps its existing
queue/stream contract.

## Shared Startup Contract

When any platform above is enabled, muGen expects:

- `mugen.modules.core.service.ingress = "default"`
- top-level `[ingress]` settings:
  - `worker_poll_seconds`
  - `worker_lease_seconds`
  - `worker_batch_size`
  - `max_attempts`
- database migrations that create:
  - `messaging_ingress_event`
  - `messaging_ingress_dedup`
  - `messaging_ingress_dead_letter`
  - `messaging_ingress_checkpoint`

The ingress service is a first-class DI provider and is part of container
readiness for external messaging platforms.

## Canonical Event Envelope

All supported platform transports are normalized into `MessagingIngressEvent`
before business processing.

Required fields:

- `version`
- `platform`
- `runtime_profile_key`
- `source_mode`
- `event_type`
- `event_id`
- `dedupe_key`
- `identifier_type`
- `identifier_value`
- `room_id`
- `sender`
- `payload`
- `provider_context`
- `received_at`

Practical rules:

- `runtime_profile_key` identifies the active transport/runtime profile that
  received the event.
- `identifier_type` and `identifier_value` carry the tenant-routing identity
  used by ingress bindings.
- `room_id` remains conversation/reply context, not the tenant-routing key.
- `provider_context` carries transport-specific metadata that should survive
  normalization without forcing provider-specific worker contracts.

## Shared Persistence Model

The shared ingress foundation uses four tables:

- `messaging_ingress_event`: durable inbox plus worker lease/status state
- `messaging_ingress_dedup`: duplicate suppression ledger
- `messaging_ingress_dead_letter`: terminal failures and replay candidates
- `messaging_ingress_checkpoint`: transport/runtime checkpoints

Current checkpoint use:

- Matrix persists sync checkpoints here with `checkpoint_key = "sync_token"`.

## Staging Transaction

Every supported transport follows the same high-level flow:

1. transport-specific auth/verification happens at the source edge;
2. transport payloads are converted into one canonical ingress event per
   logical inbound event;
3. dedupe rows and inbox rows are written in one transaction;
4. optional checkpoints are written in that same transaction;
5. transport success is returned only after the staging transaction commits.

For webhook platforms, this means HTTP success is an acknowledgement of durable
staging, not of completed business processing.

## Worker Contract

The shared ingress worker:

- claims `queued` rows, or expired `processing` rows, with a lease;
- increments attempts on claim;
- dispatches `IPCCommandRequest(platform, command, data=<canonical event>)`;
- treats IPC aggregate errors and raised exceptions as processing failures;
- requeues failed rows until `ingress.max_attempts` is reached;
- writes terminal failures to `messaging_ingress_dead_letter`;
- marks successful rows `completed`.

The transport ingress path is therefore decoupled from business handler latency
and failures.

## Normalized IPC Commands

New ingress rows target these normalized commands:

| Platform | Command | Primary `identifier_type` | Typical `source_mode` |
| --- | --- | --- | --- |
| Matrix | `matrix_ingress_event` | `recipient_user_id` | `sync_room_message`, `sync_callback` |
| LINE | `line_ingress_event` | `path_token` | `webhook` |
| Signal | `signal_ingress_event` | `account_number` | `receive_loop` |
| Telegram | `telegram_ingress_event` | `path_token` | `webhook` |
| WeChat | `wechat_ingress_event` | `path_token` | `webhook` |
| WhatsApp | `whatsapp_ingress_event` | `phone_number_id` | `webhook` |

These commands define the current public ingress-processing contract.

Older raw ingress commands and older platform-specific reliability table names
may still exist as compatibility paths in some code paths, but they are not the
current runtime contract and should not be used for new integrations.

## Replay and Operations

Operators inspect and redrive ingress through ACP-visible tables and documented
row-state mutation. This initiative does not add a separate replay API.

Operational consequences:

- backlog visibility is table-driven;
- failed and dead-letter rows are durable across restart;
- replay is based on queue/dead-letter row state, not transport redelivery.

## Change Policy

If shared ingress behavior changes in core, update this contract and the
affected platform support contracts in the same change set. At minimum, cover:

- envelope shape changes;
- shared table or worker semantic changes;
- normalized command changes;
- checkpoint behavior changes.
