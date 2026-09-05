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

## Ingress Binding Ownership

For messaging channels, an `IngressBinding` must reference an active
`ChannelProfile` in its own tenant. Its identifier must equal the corresponding
identifier of that channel's active, tenant-owned `MessagingClientProfile`.
Creation, identifier/profile changes, and reactivation validate these references.
A patch containing only `IsActive: false` can deactivate an invalid legacy binding.
Custom channels retain their own identifier conventions; any referenced channel
profile must still belong to the binding's tenant and channel.

Routing uses the authenticated client profile to derive its tenant, restrict
binding lookup, and verify that the resolved channel belongs to the same client.
Webhook path tokens and provider payload identifiers do not select another tenant.
Matrix supplies its configured receiving profile directly. Signal pins each event
to the supervisor-selected receiving profile and revalidates that profile before
routing; provider-supplied profile IDs cannot replace it. Staged webhook events
retain their canonical client profile during replay, including any fresh lookup.
A failed lookup or mismatched cached route remains a processing failure, so shared
ingress retries or dead-letters the event rather than accepting a stale fallback.
Active `(ChannelKey, IdentifierType, IdentifierValue)` combinations are globally
unique, consistent with identifier lookup for transports without explicit scope.
Messaging client identifiers already have matching global active uniqueness.

Migration `d8f2b6c4a0e1` deliberately fails if existing active bindings collide
across tenants. It preserves those rows instead of selecting an unverified owner.
Before retrying, verify each collision against the actual messaging client profile
and deactivate the invalid binding through ACP. Existing bindings whose channel
profile or identifier ownership is invalid must be corrected before reactivation.

Webhook staging fails with HTTP 500 if an event cannot resolve its client
profile. The legacy IPC path records unresolved routes in its dead-letter store
and returns a delivery failure; IPC errors also produce HTTP 500. These failures
retain provider retry behavior and are included in webhook routing-failure logs
and counters instead of acknowledging empty staging as successful delivery.

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

If human handoff is active for the resolved conversation scope, the message
handler stores the inbound user turn in context history and returns a
`control/human_handoff_active` response. Platform response dispatchers must
ignore that response and emit no user-visible fallback. See
[Human Handoff Backend Contract](./human-handoff-backend.md).

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
