# Channel Orchestration Downstream Integration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-03-06

## Context

`channel_orchestration` provides a generic ACP-managed orchestration surface for
intake, routing, throttling, policy enforcement, fallback handling, and event
timelines. Downstream plugins still own channel transport integration and
business-specific routing/escalation policy.

## Decision

- Use `channel_orchestration` ACP resources/actions as the orchestration control
  plane.
- Keep channel webhook/media/session transport logic in adapter plugins.
- Keep app-specific ownership/routing/escalation policy in downstream plugins.
- Configure behavior through orchestration data models and actions, not custom
  core orchestration forks.

## Core vs Downstream Boundary

- Core responsibilities:
  - Generic orchestration entities and actions:
    `evaluate_intake`, `route`, `escalate`, `apply_throttle`,
    `block_sender`, `unblock_sender`, `set_fallback`.
  - ACP contributor registration, runtime binding, CRUD/action surface.
  - Append-only orchestration timeline via `OrchestrationEvent`.
- Downstream responsibilities:
  - Sender/context normalization from channel payloads.
  - Business routing ownership and escalation semantics.
  - Adapter callback handlers and workflow triggering.
  - Environment-specific seed/reseed policy values.
- Why this boundary:
  - Transport behavior varies by channel.
  - Policy behavior varies by product/workflow and changes frequently.
  - Core remains stable, generic, and migration-safe.

## Implementation Sketch

### Data Model

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

Downstream stores only integration-specific metadata outside this model set.

### Services / APIs

#### Tenant-aware ingress routing

Ingress routing is resolved before orchestration actions run.

Routing identifiers currently used by adapters:

- LINE: `identifier_type="path_token"` from webhook path token.
- Telegram: `identifier_type="path_token"` from webhook path token.
- WeChat: `identifier_type="path_token"` from webhook path token.
- Signal: `identifier_type="account_number"` from normalized account number.
- WhatsApp: `identifier_type="phone_number_id"` from webhook account metadata.
- Web chat:
  - when `tenant_slug` is provided, resolve with
    `identifier_type="tenant_slug"` and `require_active_binding=False`;
  - when `tenant_slug` is omitted, use direct global route fallback.

Resolver flow (`IIngressRoutingService.resolve`):

1. Normalize request fields (`platform`, `channel_key`, `identifier_type`,
   `identifier_value`, optional `tenant_slug`, optional claims).
2. If `require_active_binding=True` and identifier is missing, fail with
   `missing_identifier`.
3. If tenant slug is provided:
   - load tenant by slug,
   - require active tenant status,
   - if `auth_user_id` is present, require active tenant membership
     (global tenant is membership-exempt).
4. If `require_active_binding=True`:
   - resolve active `IngressBinding` by
     (`channel_key`, `identifier_type`, `identifier_value`, optional tenant),
   - fail with `ambiguous_binding` when multiple active rows match,
   - fail with `inactive_binding` when only inactive rows match,
   - fail with `missing_binding` when no rows match,
   - derive tenant from binding and re-check tenant activity and membership.
5. If `require_active_binding=False` and no tenant slug is provided, use global
   tenant fallback (`tenant_slug="global"`). Web chat may short-circuit this
   path by using direct global fallback before calling resolver.
6. Resolve `route_key` with precedence:
   - `IngressBinding.attributes.route_key`
   - else `ChannelProfile.route_default_key`
   - else `None`.
7. Return ingress context envelope:
   `tenant_id`, `tenant_slug`, `platform`, `channel_key`, `identifier_claims`,
   optional `channel_profile_id`, optional `route_key`, optional `binding_id`.

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

- Webhook adapters (LINE/Telegram/WeChat/Signal/WhatsApp) dead-letter the
  payload, increment unresolved-route metrics, log warning details, and drop
  further processing.
- Web chat (`tenant_slug` override path) rejects unauthorized tenants (`403`)
  and invalid tenant slugs (`400`).

On successful resolution, attach ingress context to downstream processing:

- `message_context` item: `{"type":"ingress_route","content":{...}}`
- media/message metadata: `metadata.ingress_route={...}`

Recommended downstream ingress sequence:

1. Adapter receives inbound payload.
2. Adapter resolves tenant-aware ingress route.
3. Downstream maps payload to normalized sender/context + channel profile.
4. Call orchestration actions in sequence as needed:
   `evaluate_intake` -> `route` -> `apply_throttle`.
5. Call `escalate` or `set_fallback` on downstream business triggers.
6. Use `block_sender` and `unblock_sender` for operator or automation controls.

Use ACP HTTP/API paths (including `IngressBindings` management); do not write
orchestration tables directly.

### Operational Notes

- Seed baseline channel profiles/rules/policies per tenant.
- Keep rule priorities deterministic across environments.
- Add retry strategy for row-version conflicts on hot senders.
- Use `OrchestrationEvent` for operational debugging and downstream reporting.

## Validation

Required downstream coverage:

- Rule matching and precedence (intent/keyword/menu and priority order).
- Throttling/blocklist behavior, including unblock flows.
- Fallback policy behavior when no route is resolved.
- ACP registration/runtime binding checks.
- ACP HTTP E2E for orchestration CRUD/actions in downstream CI.

## Risks / Open Questions

- Sender identity normalization consistency across channels.
- Idempotency behavior for duplicate inbound deliveries.
- Fallback target conventions (queue vs service key) per downstream domain.
