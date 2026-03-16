# Knowledge Pack BM25 Retrieval

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-13

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
  - Scope ownership (`channel/locale/category`) and published-content immutability.
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

Create a downstream search table, for example:

- `downstream_kp_search_doc`
  - `tenant_id UUID NOT NULL`
  - `knowledge_entry_revision_id UUID NOT NULL`
  - `knowledge_pack_id UUID NOT NULL`
  - `knowledge_pack_version_id UUID NOT NULL`
  - `channel CITEXT NULL`
  - `locale CITEXT NULL`
  - `category CITEXT NULL`
  - `doc_tsv tsvector NOT NULL`
  - `title TEXT NULL`
  - `body TEXT NULL`
  - `updated_at timestamptz NOT NULL default now()`

Indexes:

- `GIN (doc_tsv)` for lexical search
- `BTREE (tenant_id, channel, locale, category)` for scope narrowing
- Unique on `(tenant_id, knowledge_entry_revision_id)`

Populate `doc_tsv` with weighted fields, e.g.:

```sql
setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
setweight(to_tsvector('english', coalesce(body, '')), 'B')
```

### Services / APIs

Downstream service flow:

1. Resolve candidate revision IDs from published/scope constraints:
   call `KnowledgeScopeService.list_published_revisions(...)`.
2. Execute BM25/`ts_rank_cd` query against projection table using those IDs.
3. Return top-k snippets and scores to downstream orchestration code.

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

### Operational Notes

- Build projection in migration + backfill job.
- Update projection on publish/archive/rollback events (or periodic reconciler).
- Never index non-published revisions in the projection table.
- Keep projection rebuild idempotent by unique revision key.

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

