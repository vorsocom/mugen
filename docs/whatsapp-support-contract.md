# WhatsApp Support Contract

This document defines the current WhatsApp Cloud API support contract in
muGen.

## Scope

- Ingress mode: webhook only.
- Webhook routes:
  - `GET /api/whatsapp/wacapi/webhook/<path_token>`
  - `POST /api/whatsapp/wacapi/webhook/<path_token>`
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
   - `whatsapp.beta.users` when `mugen.beta.active=true`
2. DI provider path resolves:
   - `mugen.modules.core.client.whatsapp`
3. required extension tokens are registered:
   - FW: `core.fw.whatsapp_wacapi`
   - IPC: `core.ipc.whatsapp_wacapi`

Webhook path tokens, verification tokens, app secrets, phone-number ids, and
Graph API access tokens are owned by ACP `MessagingClientProfiles` plus
`KeyRef` secrets. Zero active client profiles is valid at startup.

## Webhook Security Contract

Webhook ingress is guarded by all of:

1. WhatsApp platform enabled gate.
2. Optional server IP allow-list gate from root config.
3. Path token resolution through active ACP WhatsApp client profiles.
4. Subscription verification (GET) using the matched client profile verify
   token.
5. Request signature verification (POST) using the matched client profile app
   secret.
6. POST payload `phone_number_id` must match the client profile selected by the
   webhook path token.

Any verification failure is rejected before IPC dispatch.

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
