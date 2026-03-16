# Ops Case Link Target Governance

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_case` exposes generic `OpsCaseLinks` for cross-domain references and
only enforces structural validation (`TargetId` or `TargetRef`). It does not
validate external object existence, tenancy alignment, or display conventions.
Downstream plugins must own those policies.

## Decision

- Keep `OpsCaseLinks` generic in core; enforce semantic validation downstream.
- Require downstream resolver contracts per target namespace/type.
- Enforce tenant-scope checks before creating links to tenant-owned entities.
- Keep display/label normalization downstream and non-blocking for core writes.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store link records and soft-delete metadata.
  - Enforce generic create/update schema and DB constraints.
  - Expose ACP CRUD for links.
- Downstream responsibilities:
  - Validate that referenced objects exist and are tenant-accessible.
  - Resolve canonical display labels and link health status.
  - Define allowed `link_type` / `target_type` combinations per tenant domain.
- Why this boundary:
  - Cross-domain referential rules depend on downstream domain ownership.

## Implementation Sketch

### Data Model

Add downstream resolver metadata, for example:

- `downstream_case_link_policy`
  - `tenant_id UUID NOT NULL`
  - `link_type CITEXT NOT NULL`
  - `target_namespace CITEXT NULL`
  - `target_type CITEXT NOT NULL`
  - `require_target_id BOOLEAN NOT NULL DEFAULT false`
  - `enabled BOOLEAN NOT NULL DEFAULT true`

- `downstream_case_link_resolution`
  - stores resolution status (`ok`, `missing`, `forbidden`, `stale`) and
    last-validated timestamp.

### Services / APIs

1. Pre-create validator checks policy and target existence via domain adapters.
2. Write link via ACP `OpsCaseLinks` create only after validation passes.
3. Periodic resolver re-checks stored links and marks stale/missing targets.
4. UI/API enrichment reads downstream resolution status alongside core links.

### Operational Notes

- Cache resolver lookups with short TTL to reduce fan-out.
- Treat external resolver outages as retryable, not permanent failure.
- Provide admin tooling for bulk revalidation after migrations.

## Validation

- Unit tests for allowed/disallowed link policy combinations.
- Integration tests for tenant mismatch and missing-target rejection.
- E2E tests for valid create (`201`) and invalid create (`400/403`) paths.
- Periodic job tests for stale-target detection and status refresh.

## Risks / Open Questions

- Resolver latency can impact case creation throughput.
- External IDs may be recycled in some downstream domains.
- Eventual consistency windows can cause temporary false negatives.
