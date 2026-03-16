# Downstream Plugin Authoring Guardrails

Status: Draft
Last Updated: 2026-02-14
Audience: Downstream plugin maintainers

## Context

Recent downstream plugin work surfaced repeated integration and maintenance
issues that were not business-logic bugs:

- inconsistent line-length/formatting behavior across editors and CI,
- static analysis noise from unresolved forward references in model annotations,
- uncertainty about when ACP model mixins should be used versus declared fields,
- inconsistent validation workflow before merge.

These are cross-cutting implementation concerns. They should be standardized for
downstream plugins, but should not be pushed into ACP core abstractions.

## Decision

- Keep downstream plugin code in a dedicated top-level package outside the
  upstream `mugen` package whenever practical (for example `acme_extension`),
  and reserve `mugen/core` for intentional framework changes.
- Follow workspace formatter policy from `.vscode/settings.json` as the default
  formatting baseline for downstream plugin Python code.
- Prefer `TYPE_CHECKING` imports for unsuppressed forward-referenced model types
  (for example `Mapped["EntitlementBucket"]`) to satisfy Pylance without runtime
  circular imports.
- Use ACP model mixins when their semantics match exactly.
  For nullable scoping cases (for example nullable tenant association in audit),
  define fields directly in downstream model classes.
- Keep suppressions (`# type: ignore`) narrow and intentional; do not use them
  as a first response for every unresolved model reference.
- Keep partial index definitions in Alembic migrations as the source of truth.
  Do not rely on ORM-only `postgresql_where` metadata as the authoritative
  contract for downstream uniqueness semantics.
- Keep downstream plugin migrations in plugin-owned migration tracks (separate
  schema + version table), not in core `migrations/versions`.
- Run style and targeted static-analysis checks before merge.

## Core vs Downstream Boundary

- Core responsibilities:
  Provide stable ACP contracts, mixins, and extension points.
- Downstream responsibilities:
  Implement plugin-specific persistence/typing policy, runtime behavior,
  package structure, and local quality gates.
- Why this boundary:
  Core should remain reusable and strict; downstream should own plugin-specific
  tradeoffs and delivery velocity.

## Implementation Sketch

### Data Model

- Default to ACP mixins for common scoping semantics:
  `TenantScopedMixin`, `SoftDeleteMixin`, etc.
- If a plugin requires nullable scope fields, define explicit columns in the
  model instead of forcing mismatched mixins.
- For model relationships using forward references, add type-only imports:
  `from typing import TYPE_CHECKING` and import symbols inside
  `if TYPE_CHECKING:`.
- For partial indexes, define and evolve predicates in migration revisions and
  treat migration SQL as canonical for production behavior.
- Use plugin track runners for migration execution (`scripts/run_migration_tracks.py`)
  and keep core track history independent.

### Services / APIs

- No ACP API surface changes required for these guardrails.
- Apply guardrails at plugin model/service layer and in plugin-local coding
  conventions.
- Register downstream framework/plugin metadata through
  `mugen.modules.extensions`; do not assume that arbitrary new runtime
  extension classes can be loaded without matching framework-registry support.

### Operational Notes

- Treat these rules as authoring defaults for new downstream plugin files.
- For existing files, apply incrementally during touched-file edits instead of
  mass refactors unless explicitly scheduled.
- Read `docs/downstream-architecture-conformance.md` before introducing a new
  package, migration track, or extension boundary.

## Validation

- Run ACP-style checker on changed files:
  `python .codex/skills/acp-python-style/scripts/check_acp_style.py <paths...>`
- Confirm no unsuppressed unresolved `Mapped["Type"]` forward refs in changed
  files.
- Ensure warnings are addressed via `TYPE_CHECKING` imports first, not blanket
  ignores.
- Verify partial index changes through migration checks (offline SQL and
  upgrade/downgrade validation), not only model metadata review.

## Risks / Open Questions

- Different editors may still apply local formatters inconsistently if workspace
  settings are not respected.
- Some legacy files intentionally rely on inline suppressions; deciding when to
  migrate them to `TYPE_CHECKING` imports should remain a per-file judgment.
- A dedicated static check for unresolved unsuppressed `Mapped[...]` references
  may be worth adding to automation.
