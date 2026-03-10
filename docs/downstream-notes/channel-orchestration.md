# Channel Orchestration Downstream Integration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-03-08

## Context

`channel_orchestration` provides a generic ACP-managed orchestration surface for
intake, routing, throttling, policy enforcement, fallback handling, and event
timelines. Downstream plugins still own transport integration and business
policy.

## Decision

- Use `channel_orchestration` ACP resources and actions as the orchestration
  control plane.
- Keep transport webhook and session logic in adapter plugins.
- Keep app-specific routing and escalation policy downstream.
- Treat ACP `MessagingClientProfiles` as the source of truth for messaging
  transport accounts.

## Core Model

Use core ACP resources directly:

- `ChannelProfile`
- `IngressBinding`
- `IntakeRule`
- `RoutingRule`
- `OrchestrationPolicy`
- `ConversationState`
- `ThrottleRule`
- `BlocklistEntry`
- `OrchestrationEvent`

`ChannelProfile` now binds to a transport account through
`ChannelProfile.client_profile_id`.

- it selects the ACP-owned client account used for that tenant channel endpoint;
- it is required for non-web messaging channel profiles;
- it must reference an active client profile in the same tenant and platform.

## Tenant-Aware Ingress Routing

Ingress routing is resolved before orchestration actions run.

Routing identifiers used by adapters:

- LINE: `identifier_type="path_token"`
- Matrix: `identifier_type="recipient_user_id"`
- Telegram: `identifier_type="path_token"`
- WeChat: `identifier_type="path_token"`
- Signal: `identifier_type="account_number"`
- WhatsApp: `identifier_type="phone_number_id"`
- Web chat:
  - when `tenant_slug` is provided, resolve with
    `identifier_type="tenant_slug"` and `require_active_binding=False`;
  - when `tenant_slug` is omitted, use direct explicit global routing rules
    only.

Resolver success returns:

- `tenant_id`
- `tenant_slug`
- `platform`
- `channel_key`
- `identifier_claims`
- optional `channel_profile_id`
- optional `client_profile_id`
- optional `client_profile_key`
- optional `service_route_key`
- optional `route_key`
- optional `binding_id`

Service-route resolution order:

- `IngressBinding.service_route_key`
- `ChannelProfile.service_route_default_key`
- `None`

Semantics:

- `client_profile_key` remains transport-account identity.
- `service_route_key` is the tenant business surface or workflow family.
- `route_key` remains the operational queue-routing key.

Resolver failure reason codes:

- `missing_identifier`
- `missing_binding`
- `inactive_binding`
- `ambiguous_binding`
- `invalid_tenant_slug`
- `inactive_tenant`
- `unauthorized_tenant`
- `resolution_error`

Adapter behavior on unresolved route:

- Matrix, LINE, Telegram, WeChat, Signal, and WhatsApp warning-log and drop
  inbound processing before messaging handlers run.
- Web chat rejects invalid or unauthorized tenant overrides.

There is no implicit Matrix fallback to the global tenant. The global tenant is
used only when bindings or explicit orchestration rules point there.

## Recommended Downstream Sequence

1. Adapter receives inbound payload.
2. Adapter resolves tenant-aware ingress route.
3. Downstream uses `service_route_key` to pick the business workflow surface,
   then maps payload to normalized sender/context plus channel profile.
4. Call orchestration actions as needed:
   `evaluate_intake` -> `route` -> `apply_throttle`.
5. Call `escalate` or `set_fallback` on downstream business triggers.
6. Use `block_sender` and `unblock_sender` for operator or automation controls.
