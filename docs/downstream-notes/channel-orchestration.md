# Channel Orchestration Downstream Integration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

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
- `IntakeRule`
- `RoutingRule`
- `OrchestrationPolicy`
- `ConversationState`
- `ThrottleRule`
- `BlocklistEntry`
- `OrchestrationEvent`

Downstream stores only integration-specific metadata outside this model set.

### Services / APIs

Recommended downstream ingress sequence:

1. Adapter receives inbound payload.
2. Downstream maps payload to normalized sender/context + channel profile.
3. Call orchestration actions in sequence as needed:
   `evaluate_intake` -> `route` -> `apply_throttle`.
4. Call `escalate` or `set_fallback` on downstream business triggers.
5. Use `block_sender` and `unblock_sender` for operator or automation controls.

Use ACP HTTP/API paths; do not write orchestration tables directly.

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
