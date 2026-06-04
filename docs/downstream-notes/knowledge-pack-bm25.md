# Knowledge Pack BM25 Retrieval

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-06-04

## Context

`knowledge_pack` currently supports lifecycle governance and scope-bounded
retrieval of published revisions, but it does not provide lexical ranking.
Downstream plugins need deterministic keyword retrieval to reduce irrelevant
context sent to LLM generation.

## Decision

- Implement BM25-style retrieval in downstream plugins, not in core.
- Keep `knowledge_pack` as the source of truth for publish state and scope.
- Build a downstream search projection table keyed by published revision IDs.
- Filter by tenant + scope + published state before ranking.

## Core vs Downstream Boundary

- Core responsibilities:
  - Version workflow and governance (`draft/review/approved/published/archived`).
  - Scope ownership (`channel`, `locale`, `category`, `service_route_key`,
    `client_profile_key`) and published-content immutability.
  - Generic CRUD/action surface via ACP.
- Downstream responsibilities:
  - Search indexing strategy (BM25 fields, weighting, analyzers, ranking policy).
  - Query UX (thresholds, top-k, fallback behavior).
  - Domain-specific boosts (for product names, policy terms, synonyms).
- Why this boundary:
  - BM25 tokenization/weighting is domain-specific and changes frequently.
  - Keeping it downstream avoids locking core into one retrieval policy.

## Implementation Sketch

### Data Model

Create a downstream search projection. If one revision can be exposed through
multiple `KnowledgeScopes`, either store scopes in a separate projection table
or denormalize one search row per revision/scope row. For a denormalized
projection:

- `downstream_kp_search_doc`
  - `projection_doc_key TEXT PRIMARY KEY`
  - `knowledge_scope_id UUID NULL`
  - `tenant_id UUID NOT NULL`
  - `knowledge_entry_revision_id UUID NOT NULL`
  - `knowledge_pack_id UUID NOT NULL`
  - `knowledge_pack_version_id UUID NOT NULL`
  - `channel CITEXT NULL`
  - `locale CITEXT NULL`
  - `category CITEXT NULL`
  - `service_route_key CITEXT NULL`
  - `client_profile_key CITEXT NULL`
  - `doc_tsv tsvector NOT NULL`
  - `title TEXT NULL`
  - `body TEXT NULL`
  - `updated_at timestamptz NOT NULL default now()`

Indexes:

- `GIN (doc_tsv)` for lexical search
- `BTREE (tenant_id, channel, locale, category)` for legacy scope narrowing
- `BTREE (tenant_id, service_route_key, client_profile_key)` for routed/profiled
  scope narrowing
- Unique projection key per revision/scope row, or a separate scope table keyed
  by source scope identity

Populate `doc_tsv` with weighted fields, e.g.:

```sql
setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
setweight(to_tsvector('english', coalesce(body, '')), 'B')
```

### Services / APIs

Downstream service flow:

1. Resolve candidate revision IDs from published/scope constraints:
   call `KnowledgeScopeService.list_published_revisions(...)` with tenant,
   channel, locale, category, `service_route_key`, and `client_profile_key`.
2. Execute BM25/`ts_rank_cd` query against projection table using those IDs.
3. Return top-k snippets and scores to downstream orchestration code.

If a downstream projection performs scope filtering itself, route/profile
matching must mirror core semantics: supplied request values match exact values
or `NULL` fallback rows, while missing request values match only `NULL` rows for
that dimension.

Recommended SQL pattern:

```sql
SELECT s.knowledge_entry_revision_id,
       ts_rank_cd(s.doc_tsv, websearch_to_tsquery('english', :query)) AS score
FROM mugen.downstream_kp_search_doc s
WHERE s.tenant_id = :tenant_id
  AND (:channel IS NULL OR s.channel = :channel)
  AND (:locale IS NULL OR s.locale = :locale)
  AND (:category IS NULL OR s.category = :category)
  AND s.knowledge_entry_revision_id = ANY(:revision_ids)
  AND s.doc_tsv @@ websearch_to_tsquery('english', :query)
ORDER BY score DESC
LIMIT :top_k;
```

When `:revision_ids` comes from `KnowledgeScopeService`, route/profile fallback
has already been enforced. If a projection query does not pre-resolve revision
IDs, use explicit fallback predicates instead of simple equality:

```sql
AND (
      (:has_service_route_key AND
        (s.service_route_key = :service_route_key OR s.service_route_key IS NULL))
   OR (NOT :has_service_route_key AND s.service_route_key IS NULL)
)
AND (
      (:has_client_profile_key AND
        (s.client_profile_key = :client_profile_key OR s.client_profile_key IS NULL))
   OR (NOT :has_client_profile_key AND s.client_profile_key IS NULL)
)
```

### Operational Notes

- Build projection in migration + backfill job.
- Update projection on publish/archive/rollback events (or periodic reconciler).
- Never index non-published revisions in the projection table.
- Keep projection rebuild idempotent by stable projection keys or separate
  source scope keys.
- Keep `service_route_key` and `client_profile_key` in sync with the
  authoritative `KnowledgeScopes` rows; stale routed/profiled projection fields
  are a scope-leak risk.

## Validation

- Unit tests:
  - Scope + published filter is enforced before ranking.
  - Ranking order is deterministic for fixture docs.
- Integration tests:
  - Publish -> searchable.
  - Archive -> no longer searchable.
  - Rollback -> restored version becomes searchable.
- Migration checks:
  - New table/indexes pass alembic checker roundtrip.

## Risks / Open Questions

- Language handling: single dictionary (`english`) vs per-locale dictionaries.
- Query parser choice: `plainto_tsquery` vs `websearch_to_tsquery`.
- Reindex strategy for large backfills and zero-downtime rollout.
- Whether synonym expansion should be SQL-only or preprocessed downstream.
