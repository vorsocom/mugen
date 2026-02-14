# Ops SLA Calendar and Holiday Source

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_sla` supports generic business-hour windows and holiday references,
but does not manage canonical holiday catalogs, locale-specific exceptions, or
calendar publication workflows.

## Decision

- Keep holiday source-of-truth downstream.
- Materialize canonical calendar snapshots into `OpsSlaCalendars`.
- Version and publish calendar changes with explicit effective dates.
- Recompute active deadlines after calendar policy changes.

## Core vs Downstream Boundary

- Core responsibilities:
  - Persist calendar fields used by deadline math.
  - Apply stored calendar windows during deadline calculation.
- Downstream responsibilities:
  - Build/validate holiday datasets and locale mappings.
  - Govern publication rollout and rollback of calendar sets.
  - Trigger deadline recomputation policy.
- Why this boundary:
  - Holiday/legal calendars are jurisdiction and business specific.

## Implementation Sketch

### Data Model

Add downstream calendar governance tables, for example:

- `downstream_sla_calendar_catalog`
  - `tenant_id UUID NOT NULL`
  - `calendar_code CITEXT NOT NULL`
  - `version INTEGER NOT NULL`
  - `timezone CITEXT NOT NULL`
  - `business_days JSONB NOT NULL`
  - `holiday_refs JSONB NOT NULL`
  - `effective_from TIMESTAMPTZ NOT NULL`
  - `effective_to TIMESTAMPTZ NULL`

### Services / APIs

1. Validate incoming holiday package and publish catalog version.
2. Upsert `OpsSlaCalendars` via ACP CRUD from published catalog rows.
3. For affected clocks, recalculate deadlines and patch `DeadlineAt`.
4. Emit operational events for calendar publish/recompute completion.

### Operational Notes

- Run publication in maintenance windows for large tenant footprints.
- Batch deadline recomputation with pagination and retry/backoff.
- Keep prior catalog versions for fast rollback.

## Validation

- Unit tests for holiday parsing and invalid date handling.
- Integration tests for version publish + rollback.
- Boundary tests for weekend/holiday rollover after publication.

## Risks / Open Questions

- Mid-day calendar changes can surprise operators if deadlines shift abruptly.
- Timezone data drift across runtime nodes can cause inconsistent results.
