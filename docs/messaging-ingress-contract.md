# Messaging Ingress Contract

This document defines the shared durable ingress contract for external
messaging platforms in muGen core.

## Scope

The shared ingress foundation applies to:

- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

The `web` platform is out of scope.

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

Enabled messaging platforms may start with zero active ACP client profiles.

## Canonical Event Envelope

All supported platform transports are normalized into `MessagingIngressEvent`
before business processing.

Required fields:

- `version`
- `platform`
- `client_profile_id`
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

- `client_profile_id` identifies the transport account that received the event.
- `identifier_type` and `identifier_value` carry the tenant-routing identity.
- `room_id` remains conversation/reply context, not the tenant-routing key.
- `provider_context` may carry optional `client_profile_key` for logs/debugging.

## Shared Persistence Model

The shared ingress foundation uses four tables:

- `messaging_ingress_event`
- `messaging_ingress_dedup`
- `messaging_ingress_dead_letter`
- `messaging_ingress_checkpoint`

Current checkpoint use:

- Matrix persists `checkpoint_key = "sync_token"` per `client_profile_id`.

## Staging Transaction

Every supported transport follows the same high-level flow:

1. transport-specific auth and verification happens at the source edge;
2. transport payloads are converted into canonical ingress events;
3. dedupe rows and inbox rows are written in one transaction;
4. optional checkpoints are written in that same transaction;
5. transport success is returned only after the staging transaction commits.

## Worker Contract

The shared ingress worker:

- claims `queued` rows, or expired `processing` rows, with a lease;
- increments attempts on claim;
- dispatches `IPCCommandRequest(platform, command, data=<canonical event>)`;
- treats IPC aggregate errors and raised exceptions as processing failures;
- requeues failed rows until `ingress.max_attempts` is reached;
- writes terminal failures to `messaging_ingress_dead_letter`;
- marks successful rows `completed`.

## Normalized IPC Commands

| Platform | Command | Primary `identifier_type` | Typical `source_mode` |
| --- | --- | --- | --- |
| Matrix | `matrix_ingress_event` | `recipient_user_id` | `sync_room_message`, `sync_callback` |
| LINE | `line_ingress_event` | `path_token` | `webhook` |
| Signal | `signal_ingress_event` | `account_number` | `receive_loop` |
| Telegram | `telegram_ingress_event` | `path_token` | `webhook` |
| WeChat | `wechat_ingress_event` | `path_token` | `webhook` |
| WhatsApp | `whatsapp_ingress_event` | `phone_number_id` | `webhook` |

Older raw ingress commands and older platform-specific reliability tables are
not part of the current runtime contract.
