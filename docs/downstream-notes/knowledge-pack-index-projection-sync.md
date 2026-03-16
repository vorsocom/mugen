# Knowledge Pack Index Projection Sync

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

`knowledge_pack` is the system of record for governance and publication state.
Downstream BM25 retrieval needs a projection table that is synchronized with
published revisions without leaking draft/review content.

## Decision

- Build and maintain a downstream projection keyed by revision identity.
- Trigger projection updates from workflow transitions (`publish`, `archive`,
  `rollback_version`), not ad-hoc polling alone.
- Make projection writes idempotent and replay-safe.
- Add periodic drift checks between source-of-truth and projection state.

## Core vs Downstream Boundary

- Core responsibilities:
  - Authoritative workflow state and immutability rules.
  - Scope and version metadata.
  - ACP CRUD/actions and lifecycle transitions.
- Downstream responsibilities:
  - Search projection schema and indexing strategy.
  - Event consumer/reconciler implementation.
  - Rebuild/replay tooling and drift remediation.
- Why this boundary:
  - Projection design and search storage choices are retrieval-engine specific.

## Implementation Sketch

### Data Model

Create downstream projection tables, for example:

- `downstream_kp_search_doc`
  - `knowledge_entry_revision_id UUID NOT NULL`
  - `knowledge_pack_version_id UUID NOT NULL`
  - `knowledge_pack_id UUID NOT NULL`
  - `tenant_id UUID NOT NULL`
  - `channel CITEXT NULL`
  - `locale CITEXT NULL`
  - `category CITEXT NULL`
  - `title TEXT NULL`
  - `body TEXT NULL`
  - `indexed_at timestamptz NOT NULL default now()`
  - unique: `(tenant_id, knowledge_entry_revision_id)`
- `downstream_kp_projection_checkpoint`
  - `consumer_name TEXT PRIMARY KEY`
  - `last_event_id BIGINT NOT NULL`
  - `updated_at timestamptz NOT NULL`

### Services / APIs

- Subscribe to source workflow events or call a periodic reconciliation service.
- On `publish`: upsert all published revisions for the version.
- On `archive`: mark or delete projected docs for the archived version.
- On `rollback_version`: deactivate current docs and activate docs for target
  published version.

### Operational Notes

- Keep replay operation idempotent by using deterministic keys.
- Process events in-order per `knowledge_pack_id` where possible.
- Keep dead-letter queue and a manual replay command for failed events.
- Run nightly drift job comparing projected revision IDs to published IDs.

## Validation

- Publish transitions make new revisions searchable.
- Archive transitions remove archived revisions from retrieval.
- Rollback swaps active revision set to target version.
- Duplicate event delivery does not create duplicates.
- Replay from checkpoint restores identical projection state.

## Risks / Open Questions

- Whether hard-delete or soft-delete is better for historical debugging.
- Event ordering guarantees across multi-worker consumers.
- Drift reconciliation cadence vs infrastructure cost.
