# <Title>

- Status: draft
- Owner: <team-or-person>
- Last Updated: <YYYY-MM-DD>

## Context

Describe the downstream problem and why it should not be solved in core.
State where the downstream code should live (for example a top-level package
such as `acme_extension`) and why it should not live under `mugen/core`.

## Decision

State the chosen approach in 2-5 bullets.

## Core vs Downstream Boundary

- Core responsibilities:
- Downstream responsibilities:
- Why this boundary:

## Implementation Sketch

### Data Model

Describe new/changed tables, indexes, and constraints.

### Services / APIs

Describe how downstream code calls into ACP/core services and where new
downstream entry points are added. Note whether the work uses an existing core
runtime token/seam or requires an upstream framework change.

### Operational Notes

Describe rollout and backfill strategy.

## Validation

List required tests/checks and success criteria.

## Risks / Open Questions

List unresolved tradeoffs and follow-up items.
