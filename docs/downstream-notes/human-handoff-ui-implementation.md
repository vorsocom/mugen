# Human Handoff UI Implementation Note

- Status: draft
- Owner: downstream UI team
- Last Updated: 2026-06-01

## Context

Core now exposes backend-only human handoff through the
`HumanHandoffSessions` ACP resource. A downstream UI is responsible for the
operator experience: discovering active sessions, letting a human take over,
sending human-authored replies, showing transcript context, and releasing the
conversation back to AI.

This belongs downstream because the operator workspace, queue rules, assignment
UX, notification model, and business workflow are product-specific. Core owns
the durable session, context persistence, AI suppression, and channel delivery
contract.

See also: [Human Handoff Backend Contract](../human-handoff-backend.md).

## Decision

- Build the UI as a downstream operator surface backed by ACP calls.
- Treat `HumanHandoffSessions` as the source of truth for handoff state.
- Render `human_reply` events as assistant-side messages because core persists
  them with `Role = "assistant"`.
- Do not replay queued handoff user turns through AI after deactivation.
- Surface delivery failures to operators and let them choose a manual retry.

## Core vs Downstream Boundary

- Core responsibilities:
  - store durable handoff sessions;
  - enforce one active session per `TenantId + ScopeKey`;
  - suppress AI while handoff is active;
  - store inbound user turns and human replies in context history;
  - deliver text human replies to web and messaging platforms;
  - return `control/human_handoff_active` as no-op channel output.
- Downstream responsibilities:
  - operator inbox, queue, assignment, and permissions UX;
  - conversation detail screen and transcript rendering;
  - take-over/release controls;
  - human reply composer;
  - operator-visible failure notifications and retry controls;
  - optional business routing around `ServiceRouteKey`.
- Why this boundary:
  - core must remain channel and product agnostic;
  - downstream products own staffing, workflow, SLA, escalation, and UI policy.

## Implementation Sketch

### Screens

Recommended minimum screens:

- Handoff inbox:
  - shows active `HumanHandoffSessions`;
  - filters by `TenantId`, `Platform`, `ServiceRouteKey`, `Status`,
    `OwnerUserId`, and freshness;
  - highlights sessions with recent inbound user messages or failed delivery.
- Conversation detail:
  - shows transcript from `list_transcript`;
  - shows session metadata and delivery status;
  - includes a text composer while `Status = "active"`;
  - includes take-over, release, and refresh controls.
- Manual activation entry point:
  - available from an existing conversation/user detail surface;
  - submits `activate_handoff` with the original platform scope fields.

Optional product screens:

- operator assignment queue;
- supervisor view;
- failed-delivery queue;
- audit/event timeline using orchestration events.

### State Model

Use a small UI state model separate from the raw ACP entity.

```typescript
type HandoffStatus = "active" | "inactive";
type DeliveryStatus = "sent" | "failed" | null;

type HandoffSessionView = {
  id: string;
  tenantId: string;
  scopeKey: string;
  platform: string;
  roomId: string | null;
  senderId: string | null;
  conversationId: string | null;
  clientProfileId: string | null;
  serviceRouteKey: string | null;
  status: HandoffStatus;
  ownerUserId: string | null;
  reason: string | null;
  activatedAt: string;
  deactivatedAt: string | null;
  lastHumanReplyAt: string | null;
  lastDeliveryStatus: DeliveryStatus;
  lastDeliveryError: string | null;
};

type TranscriptItemView = {
  sequenceNo: number;
  role: "user" | "assistant" | string;
  content: unknown;
  messageId: string | null;
  traceId: string | null;
  source: "human_handoff_user_turn" | "human_handoff" | string;
  occurredAt: string | null;
};
```

Rendering rules:

- `Role = "user"` renders user-side.
- `Role = "assistant"` and `Source = "human_handoff"` renders
  assistant-side with optional operator attribution from UI metadata.
- Non-string `Content` should be displayed with the same fallback renderer used
  for normal structured context events.
- Treat transcript sequence numbers as the stable ordering key.

### ACP Calls

Use authenticated ACP endpoints. Exact auth and tenant selection should follow
the existing downstream ACP client patterns.

Activate handoff:

```http
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/$action/activate_handoff
Content-Type: application/json
```

```json
{
  "Platform": "web",
  "RoomId": "conversation-123",
  "SenderId": "user-456",
  "ChannelId": "web",
  "ConversationId": "conversation-123",
  "ClientProfileId": null,
  "ServiceRouteKey": "support",
  "Reason": "operator takeover",
  "Metadata": {
    "ui_session_id": "optional-ui-id"
  }
}
```

Deactivate handoff:

```http
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/deactivate_handoff
Content-Type: application/json
```

```json
{
  "Reason": "resolved by operator"
}
```

Send human reply:

```http
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/human_reply
Content-Type: application/json
```

```json
{
  "Content": "Thanks. I can help with that.",
  "MessageId": "ui-msg-123",
  "TraceId": "ui-trace-456",
  "Metadata": {
    "operator_display_name": "Support"
  }
}
```

List transcript:

```http
POST /api/core/acp/v1/tenants/{tenant_id}/HumanHandoffSessions/{session_id}/$action/list_transcript
Content-Type: application/json
```

```json
{
  "Limit": 80
}
```

### Session Discovery

Use the generic ACP resource read/list surface for
`HumanHandoffSessions`. The UI should at minimum support:

- active sessions: `Status eq 'active'`;
- current tenant scoping;
- optional `Platform` and `ServiceRouteKey` filters;
- sort by `UpdatedAt desc` or `ActivatedAt desc`;
- refresh on interval or via a downstream notification channel.

If the existing ACP client supports RGQL-style filters, prefer server-side
filtering over client-side filtering.

### Platform Scope Requirements

Manual activation must preserve the channel scope from the original
conversation. Missing or wrong scope fields create a session that will not
match future inbound turns.

| Platform | Required activation fields | Recommended fields |
| --- | --- | --- |
| `web` | `Platform`, `RoomId`, `SenderId` | `ChannelId`, `ConversationId`, `ServiceRouteKey` |
| `matrix` | `Platform`, `RoomId`, `SenderId` | `ChannelId`, `ClientProfileId`, `ServiceRouteKey` |
| `line` | `Platform`, `RoomId`, `SenderId` | `ClientProfileId`, `ServiceRouteKey` |
| `telegram` | `Platform`, `RoomId`, `SenderId` | `ClientProfileId`, `ServiceRouteKey` |
| `signal` | `Platform`, `RoomId`, `SenderId` | `ClientProfileId`, `ServiceRouteKey` |
| `wechat` | `Platform`, `RoomId`, `SenderId` | `ClientProfileId`, `ServiceRouteKey` |
| `whatsapp` | `Platform`, `RoomId`, `SenderId` | `ClientProfileId`, `ServiceRouteKey` |

For web, set `ConversationId` to the web conversation id so human replies can
append to the SSE event stream.

For messaging platforms, preserve `ClientProfileId` from ingress routing when
available so delivery uses the correct ACP-owned client account.

### Web Client Behavior

The web chat UI does not need a separate delivery channel for human replies.
Human replies arrive on the existing SSE stream as `message` events.

Expected payload shape:

```json
{
  "job_id": null,
  "conversation_id": "conversation-123",
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

Frontend behavior:

- render as assistant-side text;
- do not require `job_id` for dedupe;
- dedupe by SSE event id, then by `client_message_id` if needed;
- preserve normal SSE replay behavior with `Last-Event-ID`.

### Operator Reply Flow

Recommended flow:

1. Operator opens an active session.
2. UI calls `list_transcript`.
3. Operator enters text.
4. UI disables composer and calls `human_reply`.
5. If `DeliveryStatus = "sent"`:
   - append an optimistic message or refresh transcript;
   - clear composer.
6. If `DeliveryStatus = "failed"`:
   - keep the draft available;
   - show `DeliveryError`;
   - do not create another transcript row automatically;
   - offer retry by sending a new `human_reply` only if the operator chooses.

Do not call completion or agent APIs from this flow.

### Deactivation Flow

Recommended flow:

1. Operator selects release/end handoff.
2. UI asks for an optional reason.
3. UI calls `deactivate_handoff`.
4. UI marks the composer read-only.
5. UI refreshes the session and transcript.

After deactivation, the next inbound user turn resumes normal assistant
handling. User turns received during handoff are not replayed through AI.

### Error Handling

Recommended UI mapping:

- `400`: payload validation error; show field-level validation.
- `401` or `403`: auth/permission error; show access denied and refresh session.
- `404`: session not found; remove from active inbox after confirmation.
- `409`: session is inactive for `human_reply`; refresh session state.
- `5xx`: transient backend failure; keep operator draft and allow retry.
- `DeliveryStatus = "failed"` with `200`: reply was stored as context but
  delivery failed; show delivery error and avoid automatic duplicate sends.

### Permissions

Gate the operator console route on this session role string:

```text
com.vorsocomputing.mugen.human_handoff:operator
```

The core auth session includes that value in the frontend-visible `roles` array
when the user has the effective handoff operator permission for at least one
tenant, or when the user is a global ACP administrator. The UI does not need to
check `com.vorsocomputing.mugen.acp:administrator` directly for this route.

Server-side API authorization remains tenant-scoped:

- tenant operators can list sessions, read transcripts, send replies, activate
  handoff, and deactivate handoff only for authorized tenants;
- tenant operators receive `403` for other tenants;
- users without the operator permission receive `403`;
- global ACP administrators retain access through the effective operator
  permission.

Downstream tenant roles can grant access by granting:

```text
com.vorsocomputing.mugen.human_handoff:operator
```

A typical downstream policy:

- support operator: active-session inbox, transcript, replies, activation, and
  release for assigned tenants;
- supervisor: broader queue visibility and reassignment controls in the
  downstream UI;
- admin: all session actions and audit/event access.

Core does not enforce queue assignment semantics beyond ACP auth and action
permission checks.

### Refresh and Concurrency

The backend allows idempotent activation by scope and idempotent deactivation of
an already inactive session.

UI recommendations:

- refresh session state before sending a reply if the view has been idle;
- handle `409` by reloading session status;
- keep transcript refresh separate from reply delivery status;
- prefer server timestamps over local clocks for ordering;
- avoid assuming a single browser tab owns an active session.

## Validation

Recommended downstream UI tests:

- manual activation sends the exact platform scope fields;
- active sessions appear in the inbox;
- transcript renders user and human-assistant rows in sequence order;
- composer calls `human_reply` and handles `sent`;
- composer preserves drafts and shows errors for `DeliveryStatus = "failed"`;
- inactive sessions disable the composer;
- deactivation hides or marks the session inactive;
- web SSE human replies render as assistant-side messages with `job_id = null`;
- permissions hide or disable actions for unauthorized users.

Recommended integration checks:

- activate handoff for a web conversation, send a user message, confirm no AI
  response is emitted;
- send `human_reply`, confirm the web SSE stream receives a `message`;
- deactivate handoff, send another user message, confirm AI resumes;
- repeat a delivery failure scenario and confirm the transcript is not
  auto-duplicated.

## Risks / Open Questions

- Operator assignment and queue ownership are downstream policy decisions.
- Human replies are text-only in this implementation.
- Attachments, internal notes, and multi-operator presence require downstream
  or future core extensions.
- The backend does not replay handoff-period user turns through AI after
  deactivation by design.
