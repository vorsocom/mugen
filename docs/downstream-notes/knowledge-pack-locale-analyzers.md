# Knowledge Pack Locale Analyzers

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

BM25 quality depends on tokenization and stemming rules. `knowledge_pack` stores
locale metadata but does not enforce analyzer policy. Downstream retrieval must
choose analyzer behavior per locale.

## Decision

- Select analyzers by normalized locale, with explicit fallback rules.
- Keep analyzer mapping in downstream config, not in core plugin code.
- Reindex when analyzer policy changes.
- Reject unsupported locales or route them to a safe fallback analyzer.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store `KnowledgeScope` locale/channel/category values.
  - Guarantee published workflow state.
- Downstream responsibilities:
  - Map locale to analyzer/tokenizer configuration.
  - Maintain stopword/synonym dictionaries.
  - Operate locale-specific index build and reindex.
- Why this boundary:
  - Analyzer quality and language rules evolve frequently per product domain.

## Implementation Sketch

### Data Model

Add downstream config table, for example:

- `downstream_kp_locale_analyzer_policy`
  - `locale TEXT PRIMARY KEY`
  - `analyzer_name TEXT NOT NULL`
  - `query_parser TEXT NOT NULL`
  - `is_fallback BOOLEAN NOT NULL default false`
  - `updated_at timestamptz NOT NULL`

### Services / APIs

- Normalize incoming locale (`en-US` -> `en` fallback chain).
- Resolve analyzer policy before query execution.
- Apply same analyzer family at index time and query time.
- Expose policy version in diagnostic responses.

### Operational Notes

- Roll out analyzer updates with shadow queries before cutover.
- Track unsupported locale frequency to prioritize policy additions.
- Keep a controlled fallback (for example `simple`) for unknown locales.

## Validation

- Unit tests for locale normalization and fallback order.
- Relevance fixtures per top locales.
- Regression tests for mixed-language queries.
- Reindex validation when analyzer policy version changes.

## Risks / Open Questions

- Stemmer aggressiveness causing false-positive matches.
- Synonym dictionary governance and approval process.
- Multi-locale documents requiring composite analyzers.
