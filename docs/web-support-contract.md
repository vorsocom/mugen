# Web Platform Support Contract

## Scope
The core `web` platform client provides asynchronous chat transport over:
- `POST` for message submission
- `GET` SSE stream for acknowledgements and assistant responses
- `GET` tokenized media download endpoint

Inbound events are routed through `IMessagingService` as:
- `platform="web"`
- `room_id=<conversation_id>`
- `sender=<auth_user>`

Delivery semantics are **at-least-once**.
- Durable queue state survives restart.
- A job marked `processing` can be replayed after lease expiry.
- Duplicate deliveries are possible; frontend should dedupe by `job_id` + `client_message_id`.

## Auth
All web endpoints require ACP bearer access token via `Authorization: Bearer <token>` and use `global_auth_required`.

## Endpoints

### `POST /api/core/web/v1/messages`
Accepts `multipart/form-data` and always returns async acceptance (`202`).

All requests require:
- `conversation_id` (string)
- `client_message_id` (string)

The endpoint supports two mutually exclusive request contracts.

Legacy contract (backward compatible):
- `message_type` (`text|audio|video|file|image`)
- `text` (required for `message_type=text`)
- `file` (required for `message_type=audio|video|file|image`)
- `metadata` (optional JSON object encoded as string)

Structured contract:
- `composition_mode` (`message_with_attachments|attachment_with_caption`)
- `parts` (JSON array encoded as string)
- files uploaded as multipart keys `files[<attachment_id>]`
- `metadata` (optional JSON object encoded as string)

Structured `parts[]` items:
- text part: `{"type":"text","text":"..."}`
- attachment part:
  - `{"type":"attachment","id":"a1","caption":"optional","metadata":{...}}`

Structured semantics:
- `message_with_attachments`:
  - supports text-only, attachment-only, or mixed/interleaved text+attachments.
  - attachment captions are optional.
- `attachment_with_caption`:
  - attachment-only mode (no text parts).
  - every attachment must include a non-empty `caption`.

Routing behavior for structured payloads:
- composed payloads are routed to messaging as a single composed unit.
- messaging preprocesses attachments through inferred media handlers to gather attachment evidence.
- messaging then executes one final text synthesis pass using:
  - ordered inline attachment placeholders derived from `parts`,
  - structured attachment context,
  - media-derived evidence context.
- standard text pipeline semantics still apply, so extensions may emit additional side responses.
- zero-MH mode is supported when `mugen.messaging.mh_mode="optional"`; baseline text synthesis remains available without MH bindings.

MIME inference:
- `audio/*` -> `audio`
- `video/*` -> `video`
- `image/*` -> `image`
- otherwise -> `file`

Validation and error mapping for structured contract:
- `400` `invalid empty message`:
  - no text content and no attachments.
- `400` `invalid caption target`:
  - caption field on non-attachment part, or `attachment_with_caption` without valid captioned attachments.
- `400` `invalid attachment part`:
  - missing/blank attachment `id`, or attachment part missing uploaded blob mapping.
- `415` `unsupported media type`:
  - attachment MIME type not in `web.media.allowed_mimetypes`.
- `413` `payload too large`:
  - attachment count exceeds `web.media.max_attachments_per_message`,
  - or any file exceeds `web.media.max_upload_bytes`.
- `422` `invalid structure`:
  - duplicate attachment ids, orphan uploads, malformed structure.
- `400` `mixed legacy and structured payload fields`:
  - legacy and structured fields in one request.

Limits:
- upload size checked against `web.media.max_upload_bytes`
- attachment count checked against `web.media.max_attachments_per_message`
- MIME allow-list checked against `web.media.allowed_mimetypes`

Success response (`202`):
```json
{
  "job_id": "...",
  "conversation_id": "...",
  "accepted_at": "2026-02-16T10:00:00+00:00"
}
```

### `GET /api/core/web/v1/events?conversation_id=<id>&last_event_id=<optional>`
Streams `text/event-stream`.

Replay behavior:
- Prefer `Last-Event-ID` header.
- Fallback query string: `last_event_id`.
- Server replays events with ID greater than provided value.
- SSE IDs are emitted as `v<event_log_version>:<event_log_generation>:<event_id>`.
- Clients should persist and resend the full SSE `id` value (not just numeric suffix).
- If the resume cursor is stale/invalid, server emits a `system` event with `signal="stream_reset"` and resets replay baseline to current stream generation.
- If resume continuity is broken because retained durable events no longer cover the requested cursor, server emits `stream_reset` with reason `replay_cursor_gap` (replay path) or `poll_cursor_gap` (cross-instance poll path), then continues from the first available retained event.

Event types:
- `ack`
- `message`
- `error`
- `system`
- `thinking`

Correlation guarantees:
- `ack`, `message`, `error`, `system`, and `thinking` events always include `job_id` and `client_message_id` keys in payload data.
- Stream metadata is included as `data._stream = {version, generation}`.

Keepalive:
- SSE comment heartbeat: `: ping`
- interval: `web.sse.keepalive_seconds`

Common `stream_reset` reasons:
- `invalid_last_event_id`
- `cursor_event_log_version_mismatch`
- `cursor_stream_generation_mismatch`
- `replay_generation_changed`
- `live_generation_changed`
- `poll_generation_changed`
- `replay_cursor_gap`
- `poll_cursor_gap`

### `GET /api/core/web/v1/media/<token>`
Resolves a tokenized media URL.

Rules:
- token must exist
- token must belong to authenticated user
- token must not be expired
- referenced file must still exist

Returns file bytes when valid, else `404`.

## Frontend SSE (Fetch Stream) Example
```javascript
const token = "<access-token>";
const conversationId = "conv-123";
let lastEventId = "";

async function connect() {
  const url = new URL("/api/core/web/v1/events", window.location.origin);
  url.searchParams.set("conversation_id", conversationId);
  if (lastEventId) {
    url.searchParams.set("last_event_id", lastEventId);
  }

  const response = await fetch(url.toString(), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
    },
  });

  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .getReader();

  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      const idLine = lines.find((line) => line.startsWith("id:"));
      const eventLine = lines.find((line) => line.startsWith("event:"));
      const dataLines = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());

      if (idLine) {
        lastEventId = idLine.slice(3).trim();
      }

      const eventName = eventLine ? eventLine.slice(6).trim() : "message";
      const payload = dataLines.length > 0 ? JSON.parse(dataLines.join("\n")) : {};
      console.log(eventName, payload);
    }
  }
}
```

## Media Token TTL
`web.media.download_token_ttl_seconds` controls token lifetime.
- Expired tokens return `404`.
- Worker maintenance prunes expired token records.
- media files are pruned after `web.media.retention_seconds` when not pinned by active tokens.
