# Knowledge Pack Ranking Policy

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Downstream retrieval quality degrades if ranking rules drift across endpoints.
The project needs a deterministic ranking policy layered on top of published and
scope-filtered `knowledge_pack` content.

## Decision

- Use a staged ranking pipeline: hard filters -> lexical score -> tie-breakers.
- Keep ranking explainable; no hidden dynamic boosts.
- Make business boosts explicit and versioned.
- Maintain stable tie-break behavior for deterministic tests.

## Core vs Downstream Boundary

- Core responsibilities:
  - Guarantee only valid published content enters candidate sets.
  - Expose scope metadata for filtering.
- Downstream responsibilities:
  - Define ranking equations, boosts, and tie-break rules.
  - Decide query-time thresholds and fallback behavior.
  - Version and communicate ranking policy changes.
- Why this boundary:
  - Ranking policy is product-dependent and iterates faster than core releases.

## Implementation Sketch

### Data Model

Optional downstream config table:

- `downstream_kp_ranking_policy`
  - `policy_version TEXT PRIMARY KEY`
  - `title_weight NUMERIC NOT NULL`
  - `body_weight NUMERIC NOT NULL`
  - `recency_boost NUMERIC NOT NULL`
  - `category_boost_map JSONB NOT NULL`
  - `created_at timestamptz NOT NULL`

### Services / APIs

Pipeline:
1. Filter by tenant/channel/locale/category and published state.
2. Compute lexical score (BM25 or equivalent).
3. Apply bounded boosts (category, recency, source quality).
4. Tie-break by deterministic keys (score desc, published_at desc, revision_id).

Return debug metadata for internal users:

- `policy_version`
- `raw_score`
- `boost_components`

### Operational Notes

- Guard policy changes with offline evaluation fixtures.
- Roll out policy changes behind a feature flag.
- Keep policy version in logs for post-release diagnosis.

## Validation

- Golden dataset tests for ranking order.
- A/B comparison between old/new policy on replayed queries.
- Determinism tests under concurrent query load.
- Regression tests for strict scope isolation.

## Risks / Open Questions

- Over-boosting recency can suppress authoritative older content.
- Weight tuning can bias toward noisy short documents.
- Whether to add semantic reranking in downstream later.
