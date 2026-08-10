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

### Supported webhook fields

The customer-message ingress path supports only `change.field="messages"`:

- inbound customer messages are staged as message events;
- sent, delivered, read, and failed delivery updates are staged as status
  events;
- every `messages` change requires matching phone-number metadata, including
  when one webhook contains multiple entries or changes.

Authenticated non-message fields are WABA-level events and do not use phone
number routing. Fields such as `message_template_status_update`,
`account_update`, and `phone_number_quality_update` are acknowledged with HTTP
200 and intentionally ignored. They are never passed to customer-message IPC
or ingress staging, and no default phone number is used. A future supported
WABA-level field must have its own handler and resolver instead of reusing the
customer-message route.

Deployments that process only customer conversations should subscribe the Meta
app to the `messages` webhook field. Subscribe to WABA-level fields only when a
separate consumer is available; until then, authenticated deliveries are still
safely acknowledged to prevent repeated retries.

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
- `unsupported_change_field` for authenticated WABA-level changes acknowledged
  without dispatch;
- `message_event_accepted` for successfully dispatched message/status changes;
- `routing_failure` for sanitized downstream dispatch failures.

Process-local low-cardinality counters track received and authenticated
requests plus rejected, ignored, and accepted changes. Rejections are grouped
only by reason code; ignored and accepted changes are grouped by normalized
change field. Unknown field names collapse to `unknown`.

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
