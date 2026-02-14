# Ops Metering Idempotency And Replay

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Operational usage pipelines are often at-least-once. `ops_metering` supports
idempotency keys and deterministic rating/billing references, but downstream
producers and replay jobs need a concrete contract for safe retries and backfills.

## Decision

- Require producer-owned idempotency key generation for external ingest paths.
- Use stable replay keys per logical usage fact, not per delivery attempt.
- Treat duplicate ingest as success with existing row return semantics.
- Keep replay jobs append-safe and dry-run capable.

## Core vs Downstream Boundary

- Core responsibilities:
  - Enforce unique idempotency constraints and safe action idempotency behavior.
  - Preserve usage/rating/billing reference linkage.
- Downstream responsibilities:
  - Define idempotency key schema and producer conformance.
  - Run replay/backfill orchestration with chunking and checkpoints.
  - Monitor duplicate and conflict rates.
- Why this boundary:
  - Producer topology and replay semantics differ per deployment.

## Implementation Sketch

### Data Model

Add downstream ingest ledger, for example:

- `downstream_metering_ingest_ledger`
  - `tenant_id UUID NOT NULL`
  - `source_system CITEXT NOT NULL`
  - `source_event_id CITEXT NOT NULL`
  - `idempotency_key CITEXT NOT NULL`
  - `usage_record_id UUID NULL`
  - `first_seen_at timestamptz NOT NULL`
  - `last_seen_at timestamptz NOT NULL`
  - `seen_count BIGINT NOT NULL DEFAULT 1`
- Unique `(tenant_id, source_system, source_event_id)`.

### Services / APIs

1. Producer computes deterministic key (tenant + source + logical event id).
2. Ingest writes/reads `OpsUsageRecords` using `IdempotencyKey`.
3. Replay job reuses same key space and records replay batch id.
4. Conflicts/duplicates are logged as counters, not treated as failures.

### Operational Notes

- Provide replay command with `--from`, `--to`, `--tenant`, `--dry-run`.
- Keep checkpointing per source partition to support resumable replay.
- Alert on sustained idempotency miss spikes.

## Validation

- Unit tests for key builder determinism and normalization.
- Integration test: duplicate deliveries collapse to one usage record.
- Replay test: rerun same batch without creating net-new usage rows.

## Risks / Open Questions

- Key format evolution and backward compatibility.
- Source systems that cannot provide stable logical event ids.
- Replay ordering requirements for dependent usage streams.
