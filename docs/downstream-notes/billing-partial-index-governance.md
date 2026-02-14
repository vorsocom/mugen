# Billing Partial Index Governance

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Billing relies on partial unique indexes for soft-delete-aware natural keys and
nullable external references. These indexes are PostgreSQL-specific and are
part of migration/runtime database contracts. Downstream contributors need a
clear policy to avoid schema drift during model refactors.

## Decision

- Keep partial index behavior migration-first and migration-verified.
- Treat Alembic revisions as the source of truth for `postgresql_where`
  conditions and index names.
- When index predicates or uniqueness semantics change, create a new migration
  revision instead of ad-hoc runtime changes.
- Include partial-index checks in migration review and roundtrip validation.

## Core vs Downstream Boundary

- Core responsibilities:
  - Define and evolve partial index DDL in billing migrations.
  - Keep downgrade/upgrade paths explicit and reproducible.
  - Maintain cross-table naming/predicate consistency.
- Downstream responsibilities:
  - Propose new predicates/business uniqueness rules.
  - Validate query and write paths against existing index behavior.
  - Coordinate rollout windows for potentially expensive index rebuilds.
- Why this boundary:
  - Partial-index semantics are database-specific operational concerns and need
    migration discipline.

## Implementation Sketch

### Data Model

Current migration-owned partial index patterns include:

- Soft-delete-aware uniqueness (for example active-code or active-number keys):
  - `a655f4dcaa93_billing_constraints_and_indexes`
- Nullable external reference uniqueness:
  - `9c4211adf09d_billing_payment_allocations`
  - `d8a9f3c1e52b_billing_entitlements_and_usage_allocations`
  - `f7b1c2d3e4a5_billing_runs_adjustments_and_meter_codes`

### Services / APIs

No special API surface is required. CRUD/action services consume these
constraints implicitly through normal writes.

### Operational Notes

- Review migration SQL plans before production rollout when adding/changing
  partial indexes.
- Run migration roundtrip checks for billing revisions before merge.
- Capture conflict/error metrics where downstream writes hit uniqueness limits.

## Validation

- Alembic graph and static checks pass for billing revisions.
- Offline SQL generation includes expected partial index DDL.
- Upgrade/downgrade roundtrip preserves index names and predicates.

## Risks / Open Questions

- Predicate changes can silently alter accepted write behavior.
- Large-tenant index rebuild operations may need phased rollout planning.
