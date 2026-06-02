# Human Handoff Backend Contract

## Scope

Human handoff is a backend-only `channel_orchestration` capability for
conversation-scoped human takeover.

When handoff is active for a conversation scope:

- inbound user turns are persisted in context history;
- inbound user turns do not run AI completion or agent execution;
- channel dispatchers receive a control response and must not emit fallback
  messages;
- human replies are persisted as assistant-role context events;
- human replies are delivered to the original channel as text;
- normal assistant handling resumes on the next user turn after deactivation.

The first implementation is text-only for human replies. UI and operator
experience are downstream-owned.

## Runtime Model

The durable resource is `HumanHandoffSessions`.

Important fields:

- `TenantId`
- `ScopeKey`
- `Platform`
- `ChannelId`
- `RoomId`
- `SenderId`
- `ConversationId`
- `ClientProfileId`
- `ServiceRouteKey`
- `Status`
- `OwnerUserId`
- `Reason`
- `ActivatedAt`
- `DeactivatedAt`
- `DeactivatedByUserId`
- `DeactivationReason`
- `LastHumanReplyAt`
- `LastDeliveryStatus`
- `LastDeliveryError`
- `Attributes`

The database enforces one active handoff session per `TenantId + ScopeKey`.
Activating handoff for a scope with an existing active or inactive session
updates that session instead of creating parallel active ownership.

`ScopeKey` is derived from the normalized context scope. Downstream callers
should pass the same platform and conversation identifiers used by the original
channel adapter so active-handoff checks match subsequent inbound user turns.

## Activation Sources

Handoff can be activated in two ways:

- the assistant or agent returns a structured `HANDOFF` outcome;
- an operator or UI layer calls the `activate_handoff` ACP action.

Agent-triggered activation is handled by the default text message handler after
agent execution. Activation failures are warning-logged and do not prevent the
current assistant response from being returned.

## ACP Actions

All payloads use PascalCase field names.

### Activate Handoff

Entity-set action:

```text
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/$action/activate_handoff
```

Payload:

```json
{
  "Platform": "web",
  "RoomId": "conversation-or-room-id",
  "SenderId": "user-or-sender-id",
  "ChannelId": "optional-channel",
  "ConversationId": "optional-web-conversation-id",
  "ClientProfileId": "optional-client-profile-guid",
  "ServiceRouteKey": "optional-route-key",
  "Reason": "optional operator-visible reason",
  "Metadata": {
    "optional": "operator metadata"
  }
}
```

Required fields:

- `Platform`
- `RoomId`
- `SenderId`

Response:

```json
{
  "Decision": "active",
  "HumanHandoffSessionId": "session-guid",
  "ScopeKey": "stable-scope-key"
}
```

### Deactivate Handoff

Entity action:

```text
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/deactivate_handoff
```

Payload:

```json
{
  "Reason": "optional close reason"
}
```

Response:

```json
{
  "Decision": "inactive"
}
```

Deactivation does not replay queued user turns through AI. The user turns
received during handoff remain in context history and influence future context
normally.

### Human Reply

Entity action:

```text
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/human_reply
```

Payload:

```json
{
  "Content": "Text sent by the human operator",
  "MessageId": "optional-ui-message-id",
  "TraceId": "optional-trace-id",
  "Metadata": {
    "optional": "operator metadata"
  }
}
```

`Content` is required and must be non-empty.

Response:

```json
{
  "Decision": "replied",
  "DeliveryStatus": "sent",
  "DeliveryError": null
}
```

If delivery fails after context persistence, the response uses:

```json
{
  "Decision": "replied",
  "DeliveryStatus": "failed",
  "DeliveryError": "RuntimeError: delivery failure details"
}
```

The assistant-role context event is not duplicated on delivery retry. A failed
delivery records orchestration metadata and updates the session delivery status.

### List Transcript

Entity action:

```text
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/list_transcript
```

Payload:

```json
{
  "Limit": 40
}
```

`Limit` is optional. The backend applies a bounded maximum.

Response:

```json
{
  "Items": [
    {
      "SequenceNo": 1,
      "Role": "user",
      "Content": "Hello",
      "MessageId": "optional-message-id",
      "TraceId": "optional-trace-id",
      "Source": "human_handoff_user_turn",
      "OccurredAt": "2026-06-01T12:00:00+00:00"
    },
    {
      "SequenceNo": 2,
      "Role": "assistant",
      "Content": "A human response",
      "MessageId": "optional-message-id",
      "TraceId": "optional-trace-id",
      "Source": "human_handoff",
      "OccurredAt": "2026-06-01T12:01:00+00:00"
    }
  ],
  "Count": 2
}
```

## Context Semantics

Active handoff user turns are appended to `ContextEventLog` with:

- `Role = "user"`
- `Source = "human_handoff_user_turn"`

Human replies are appended to `ContextEventLog` with:

- `Role = "assistant"`
- `Source = "human_handoff"`

The context snapshot revision is advanced for both event types. This keeps
future context preparation consistent after handoff deactivation and avoids
normal AI commit collisions.

Human replies are stored as assistant-role events intentionally. Downstream
model prompts and transcript views should treat them as assistant conversation
history authored by a human.

## Control Response Contract

When an inbound user turn arrives while handoff is active, the default text
handler returns:

```json
{
  "type": "control",
  "op": "human_handoff_active",
  "human_handoff_session_id": "session-guid-or-null",
  "scope_key": "stable-scope-key"
}
```

Channel response dispatchers must treat this as no-op delivery. They must not
send fallback text, error text, or any user-visible placeholder for this
response.

Core dispatchers currently ignore this response for:

- web
- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

Downstream dispatchers should implement the same rule for any custom platform.

## Delivery Semantics

Human replies are delivered after the assistant-role context event is stored.

Delivery requirements by platform:

| Platform | Required session fields | Delivery behavior |
| --- | --- | --- |
| `web` | `ConversationId` | Appends an SSE `message` event to the web conversation stream. |
| `matrix` | `RoomId` | Sends a text response through the Matrix client. |
| `line` | `SenderId` or `RoomId` | Sends text through the LINE client. |
| `telegram` | `SenderId` or `RoomId` | Sends text through the Telegram client. |
| `signal` | `SenderId` or `RoomId` | Sends text through the Signal client. |
| `wechat` | `SenderId` or `RoomId` | Sends text through the WeChat client. |
| `whatsapp` | `SenderId` or `RoomId` | Sends text through the WhatsApp client. |

For non-web messaging platforms, `ClientProfileId` is applied through the
client-profile runtime scope when present. Downstream UI should preserve the
`ClientProfileId` resolved during ingress when activating handoff manually.

Unsupported platforms return `DeliveryStatus = "failed"` for `human_reply`.

## Web UI Integration

The web backend appends human replies as normal SSE `message` events. The event
payload includes:

```json
{
  "job_id": null,
  "conversation_id": "conversation-id",
  "client_message_id": "human-generated-id",
  "message": {
    "type": "text",
    "content": "Human reply"
  },
  "human_handoff": {
    "metadata": {}
  }
}
```

Frontend clients should render this as an assistant-side message. `job_id` is
`null` because the human reply is not produced by an async user-message queue
job.

## Downstream UI Responsibilities

A human handoff UI should:

- discover active sessions through the ACP `HumanHandoffSessions` resource;
- create sessions with `activate_handoff` when an operator takes over manually;
- show transcript history through `list_transcript`;
- send operator text through `human_reply`;
- call `deactivate_handoff` when the operator releases the conversation;
- keep platform scope fields aligned with the original channel adapter;
- surface `DeliveryStatus = "failed"` to the operator without creating another
  assistant context turn automatically.

The UI should not call model or agent APIs for queued user turns received during
active handoff. The backend intentionally does not replay those turns.

## Operational Events

The service appends orchestration events for:

- `activate_handoff`
- `deactivate_handoff`
- `human_reply`

Delivery failures are recorded as `human_reply` orchestration events with
`decision = "failed"` and an error reason. These events are operational audit
metadata; the conversation transcript source of truth remains context history.
