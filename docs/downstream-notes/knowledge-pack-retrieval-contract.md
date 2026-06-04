# Knowledge Pack Retrieval Contract

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-06-04

## Context

Different channels will consume `knowledge_pack` content differently. Without a
stable downstream retrieval contract, each channel can implement incompatible
filters, ranking semantics, and citation payloads.

## Decision

- Define one downstream retrieval contract for all channel orchestrators.
- Enforce published-only and scope-bounded filtering before ranking.
- Include governance identifiers in responses for auditability.
- Keep retrieval contract read-only against `knowledge_pack`.
- Treat `service_route_key` and `client_profile_key` as first-class optional
  scope inputs for routed traffic.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store and govern pack/version/revision state.
  - Expose resource/action surface through ACP.
  - Prevent mutation of published revisions.
- Downstream responsibilities:
  - Define retrieval API payloads and transport protocol.
  - Map channel context into scope filters, including route/profile metadata
    when present.
  - Return ranked citations and snippets.
- Why this boundary:
  - Response shape and integration transport are consumer-specific.

## Implementation Sketch

### Data Model

Reuse downstream projection rows with:

- revision identifiers
- scope columns
- searchable text fields
- precomputed ranking metadata as needed

Projection schemas should carry `service_route_key` and `client_profile_key`
when downstream retrieval needs routed/profiled isolation. Existing generic rows
with `NULL` route/profile fields remain fallback candidates.

A revision may be bound to multiple `KnowledgeScopes`. Downstream projections
must preserve those scope rows, either by storing a separate scope projection or
by denormalizing one searchable document per revision/scope row.

### Services / APIs

Recommended request payload:

```json
{
  "query": "billing dispute window",
  "tenant_id": "uuid",
  "channel": "whatsapp",
  "locale": "en-US",
  "categories": ["billing-policy"],
  "service_route_key": "support.primary",
  "client_profile_key": "whatsapp-a",
  "top_k": 10,
  "min_score": 0.0
}
```

Recommended response payload:

```json
{
  "results": [
    {
      "knowledge_entry_revision_id": "uuid",
      "knowledge_pack_version_id": "uuid",
      "title": "string",
      "snippet": "string",
      "score": 12.34
    }
  ],
  "filters_applied": {
    "tenant_id": "uuid",
    "channel": "whatsapp",
    "locale": "en-US",
    "categories": ["billing-policy"],
    "service_route_key": "support.primary",
    "client_profile_key": "whatsapp-a"
  }
}
```

### Scope Semantics

Candidate resolution must use `KnowledgeScopeService.list_published_revisions`
or the same semantics in a downstream projection:

- only published versions and published revisions are eligible;
- tenant filtering is mandatory;
- `channel`, `locale`, and `category` preserve the current exact-filter
  behavior when the caller supplies values;
- for `service_route_key` and `client_profile_key`, a supplied request value
  matches exact scope values plus `NULL` generic fallback scopes;
- when the request omits `service_route_key` or `client_profile_key`, only
  `NULL` scope values match for that dimension;
- duplicate scope matches must return each revision once, with more-specific
  route/profile matches ordered before generic matches.

### Operational Notes

- If no result matches, return empty results instead of draft fallback.
- Log query hash, filter keys, and candidate counts (no raw sensitive text).
- Keep contract versioning (`v1`, `v2`) when fields or ranking semantics change.

## Validation

- Contract tests for request/response schema.
- Integration tests proving scope filters are always enforced.
- Regression tests for stable tie-break ordering with fixed fixtures.
- Security tests proving no unpublished rows are returned.

## Risks / Open Questions

- Standardizing score normalization across different storage backends.
- Whether `matched_terms` should be surfaced or stay internal.
- How aggressively to truncate snippets for channel payload limits.
