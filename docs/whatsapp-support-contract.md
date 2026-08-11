# WhatsApp Support Contract

This document defines the current WhatsApp Cloud API support contract in
muGen.

## Scope

- Ingress mode: webhook only.
- Webhook routes:
  - `GET /api/whatsapp/wacapi/webhook/<path_token>`
  - `POST /api/whatsapp/wacapi/webhook/<path_token>`
- Flow Data route:
  - `POST /api/whatsapp/wacapi/flow-data/<path_token>`
- Multiple active WhatsApp client profiles may run concurrently in one
  deployment.
- Supported inbound event families:
  - `messages`
  - `statuses`

## Configuration And ACP

When `whatsapp` is enabled in `mugen.platforms`, startup is fail-closed unless:

1. root config has valid process-level WhatsApp settings:
   - `whatsapp.graphapi.base_url`
   - `whatsapp.graphapi.version`
   - `whatsapp.graphapi.timeout_seconds`
   - `whatsapp.graphapi.max_download_bytes`
   - `whatsapp.graphapi.typing_indicator_enabled`
   - `whatsapp.graphapi.max_api_retries` (optional)
   - `whatsapp.graphapi.retry_backoff_seconds` (optional)
   - `whatsapp.servers.verify_ip`
   - `whatsapp.servers.allowed` when `verify_ip=true`
   - `whatsapp.servers.trust_forwarded_for`
   - `whatsapp.webhook.dedupe_ttl_seconds`
2. DI provider path resolves:
   - `mugen.modules.core.client.whatsapp`
3. required extension tokens are registered:
   - FW: `core.fw.whatsapp_wacapi`
   - IPC: `core.ipc.whatsapp_wacapi`

Webhook path tokens, verification tokens, app secrets, phone-number ids, and
Graph API access tokens are owned by ACP `MessagingClientProfiles` plus
`KeyRef` secrets. Zero active client profiles is valid at startup.
An optional WABA identity can be stored in the client profile setting
`business.waba_id`; when configured, every authenticated `entry.id` must match
it before any change is dispatched.
WhatsApp Flow Data private key material is also profile-owned through
`flows.private_key` and optional `flows.private_key_passphrase` `KeyRef`
secret paths.

Optional sender gating is owned per `MessagingClientProfiles.settings` using
`user_access.mode`, `user_access.users`, and optional
`user_access.denied_message`.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WhatsApp platform enabled gate.
2. Optional server IP allow-list gate from root config.
3. Path token resolution through active ACP WhatsApp client profiles.
4. Subscription verification (GET) using the matched client profile verify
   token.
5. POST raw-body authentication using `X-Hub-Signature-256` and the matched
   client profile app secret, before JSON parsing or event classification.
6. Per-change routing validation after authentication. Every `messages` change
   must contain `value.metadata.phone_number_id`, and that id must match the
   client profile selected by the webhook path token.

Any verification failure is rejected before IPC dispatch.

### Webhook field routing

The customer-message ingress path supports `change.field="messages"`:

- inbound customer messages are staged as message events;
- sent, delivered, read, and failed delivery updates are staged as status
  events;
- every `messages` change requires matching phone-number metadata, including
  when one webhook contains multiple entries or changes.

All syntactically valid authenticated change fields are also offered to the
`whatsapp_webhook_change_registry` extension service. Exact field handlers and
the optional `*` wildcard can observe `messages`, `flows`, template updates,
account updates, phone-quality updates, and future Meta fields without a core
allowlist update. Exact and wildcard handlers run in their global registration
order. One handler failure does not prevent later independent handlers from
running.

Non-message changes are control-plane events and never enter customer-message
IPC, ingress staging, or the agent runtime merely because they were delivered.
They do not require `value.metadata.phone_number_id`, and the framework never
derives or selects a default phone number for them. A downstream handler must
explicitly own any further routing. `messages` changes still follow established
ingress even when an extension handler also observes them.

When no extension handler matches a non-message field, the request is
acknowledged with HTTP 200 and reason `no_registered_handler`. Intentional
ignores and successful handlers also return HTTP 200. Permanent handler
validation failures are sanitized and acknowledged with HTTP 200 to prevent a
futile retry. If any handler reports a retryable failure or raises unexpectedly,
all remaining matching handlers are attempted and the request returns HTTP 500
so Meta can retry it.

Deployments that process only customer conversations should subscribe the Meta
app only to the `messages` field. Subscribe to `flows`, template, account, or
other control-plane fields when a corresponding extension handler or wildcard
observer is registered. Unhandled authenticated fields remain safely
acknowledged to prevent repeated retries.

### Downstream webhook change handlers

The WACAPI framework extension creates the registry before importing the
webhook endpoint. Downstream FW plugins register handlers through
`di.EXT_SERVICE_WHATSAPP_WEBHOOK_CHANGE_REGISTRY`:

```python
from mugen.core import di
from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeOutcome,
)


async def observe_flow_lifecycle(event):
    # Product policy and persistence belong downstream.
    await record_flow_health(event)
    return WhatsAppWebhookChangeOutcome.HANDLED


async def setup(app) -> None:
    registry = di.container.get_ext_service(
        di.EXT_SERVICE_WHATSAPP_WEBHOOK_CHANGE_REGISTRY
    )
    registry.register_handler(
        observe_flow_lifecycle,
        change_field="flows",
    )
```

Each handler receives a frozen `WhatsAppWebhookChangeEnvelope` containing:

- `request_id` and the stable truncated SHA-256 `payload_fingerprint`;
- resolved non-secret `client_profile_id` and normalized `object_type`;
- Meta's WABA `entry_id` and optional `entry_time`;
- zero-based `entry_index` and `change_index`;
- the original syntactically valid `change_field`;
- a deeply immutable `change_value` mapping.

The envelope deliberately excludes headers, path tokens, signatures, app
secrets, access tokens, and verification material. `change_value` can contain
customer data and must never be logged wholesale.

Handlers return `handled`, `ignored`, `permanent_failure`, or
`retryable_failure`, preferably through `WhatsAppWebhookChangeOutcome`.
Unexpected exceptions and unsupported return values are classified as
retryable failures without logging exception text. A wildcard handler is
registered with `change_field="*"` and receives the original unknown field even
though logs and metrics normalize that field to `unknown`.

Meta delivery is at least once. Handlers must tolerate duplicates and should
form an idempotency key from `payload_fingerprint`, `entry_index`, and
`change_index`. Identical retries expose the same values.

Do not confuse `field="flows"` lifecycle/control-plane events with completed
customer Flow submissions. A customer completion arrives under
`field="messages"` as `interactive.nfm_reply` and continues through normal
message ingress.

### Webhook diagnostics

Webhook logs contain only a generated request id, a truncated SHA-256 payload
fingerprint, normalized object type, entry/change counts, normalized distinct
change fields, outcome, HTTP status, safe reason code, elapsed milliseconds,
and the resolved non-secret client-profile id. Identical raw request bodies
produce the same fingerprint, so operators can correlate Meta retries without
storing or logging the payload. Different bodies produce different
fingerprints.

Reason codes include:

- `missing_signature` and `invalid_signature` for authentication failures;
- `profile_resolution_failed` when the path-selected profile or secret cannot
  be resolved;
- `malformed_json` and `malformed_payload` for authenticated invalid input;
- `missing_phone_number_id_for_messages` and `phone_number_id_mismatch` for
  authenticated message-routing failures;
- `no_registered_handler` for authenticated changes with no extension handler;
- `change_handler_handled` and `change_handler_ignored` for completed extension
  dispatch;
- `permanent_handler_failure` for a sanitized non-retryable handler failure;
- `retryable_handler_failure` for a handler or systemic failure that returns
  HTTP 500;
- `waba_id_mismatch` for a configured WABA identity mismatch;
- `message_event_accepted` for successfully dispatched message/status changes;
- `routing_failure` for sanitized downstream dispatch failures.

Process-local low-cardinality counters track received and authenticated
requests plus rejected, ignored, and accepted changes. Rejections are grouped
only by safe reason code; ignored and accepted changes are grouped by normalized
change field. Framework-recognized fields retain their name and all future or
arbitrary fields collapse to `unknown`. Recognized safe control-plane event
types may be logged; arbitrary event values normalize to `unknown`.

Logs never contain raw webhook bodies or Graph responses, message or media
content, sender/recipient phone numbers, phone-number ids, path tokens,
signatures, app secrets, access tokens, or customer template parameters.

## Flow Data Endpoint Contract

Flow Data endpoint ingress is guarded by all of:

1. WhatsApp platform enabled gate.
2. Optional server IP allow-list gate from root config.
3. Path token resolution through active ACP WhatsApp client profiles.
4. Request signature verification using the matched client profile app secret.
5. Flow Data envelope decryption using the matched client profile
   `flows.private_key` secret.

The endpoint supports the built-in `ping` health check and delegates
non-health-check data exchange requests to the
`whatsapp_flow_data_registry` extension service. Product-specific handlers own
screen data and validation; completed Flow replies continue through the normal
webhook message path as `whatsapp_flow_reply` metadata.

Endpoint-specific errors use WhatsApp Flow client semantics:

- `421` when encrypted request material cannot be decrypted.
- `432` when request signature verification fails.
- `427` when a downstream handler reports an invalid or expired Flow token.

## Downstream Flow Data Handler Development

Flow Data handlers are registered by downstream FW plugins through the DI
extension service named by
`di.EXT_SERVICE_WHATSAPP_FLOW_DATA_REGISTRY`. The core
`core.fw.whatsapp_wacapi` extension creates the registry during setup before
importing the Flow Data endpoint.

Downstream plugins should import the public contract from
`mugen.core.plugin.whatsapp.wacapi.flow_data`:

```python
from mugen.core import di
from mugen.core.plugin.whatsapp.wacapi.flow_data import (
    WhatsAppFlowDataInvalidTokenError,
    WhatsAppFlowDataRequest,
)


async def booking_flow_data_handler(
    request: WhatsAppFlowDataRequest,
) -> dict:
    if request.flow_token is None:
        raise WhatsAppFlowDataInvalidTokenError("Flow token is required.")

    return {
        "screen": "CONFIRM",
        "data": {
            "available": True,
        },
    }


async def setup(app) -> None:
    registry = di.container.get_ext_service(
        di.EXT_SERVICE_WHATSAPP_FLOW_DATA_REGISTRY
    )
    registry.register_handler(
        booking_flow_data_handler,
        flow_name="booking",
        action="data_exchange",
        screen="DETAILS",
    )
```

Handlers receive a `WhatsAppFlowDataRequest` with:

- resolved ACP context: `tenant_id`, `client_profile_id`,
  `client_profile_key`, `phone_number_id`, and `path_token`
- decrypted Flow fields: `flow_token`, `flow_name`, `action`, `screen`, `data`,
  and `raw_payload`
- the merged profile runtime config in `runtime_config`

Handlers must return a JSON-object-compatible `dict`. Return `None` only when
the handler intentionally declines the request and another registered handler
should be tried. If no handler returns a payload, the request fails closed.

Matching is optional and additive. A handler registered with `flow_name`,
`action`, and `screen` is more specific than one registered only with
`action`; the most specific matching handler runs first. The built-in `ping`
response and client-reported `data.error` acknowledgement run before downstream
dispatch and do not call product handlers.

Token validation belongs in the downstream handler. Raise
`WhatsAppFlowDataInvalidTokenError("...")` to return WhatsApp HTTP `427` with
an `error_msg` body. Do not perform Flow completion side effects here; completed
Flow replies arrive later through the normal webhook path.

ACP setup for each WhatsApp client profile must provide:

- a path token and phone-number id on the profile
- `app.secret` as a `SecretRefs` entry
- `flows.private_key` as a `SecretRefs` entry
- `flows.private_key_passphrase` only when the private key is encrypted

Recommended downstream tests:

- unit-test handlers directly with a constructed `WhatsAppFlowDataRequest`
- verify handler registration uses the expected `flow_name`, `action`, and
  `screen`
- cover invalid token handling by asserting
  `WhatsAppFlowDataInvalidTokenError`
- keep domain side effects on webhook `whatsapp_flow_reply` handling tests

## Reliability Contract

- Each accepted WhatsApp message or status becomes one canonical ingress row
  with:
  - `platform="whatsapp"`
  - `source_mode="webhook"`
  - `identifier_type="phone_number_id"`
  - `ipc_command="whatsapp_ingress_event"`
- Shared dedupe is scoped by `platform + client_profile_id + dedupe_key`.
- HTTP success is returned only after staging commits.
- IPC failures are retried by the shared worker and dead-lettered after the
  shared attempt budget.
