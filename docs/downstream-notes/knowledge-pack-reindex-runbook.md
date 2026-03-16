# Knowledge Pack Reindex Runbook

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Analyzer changes, ranking updates, and schema evolution require safe reindexing
of downstream search projections. Without a runbook, reindex operations can
cause stale results or downtime.

## Decision

- Support full and incremental reindex flows.
- Use dual-index or versioned-index cutover for zero/low downtime.
- Keep rollback path documented and rehearsed.
- Track reindex progress with checkpoints and reconciliation metrics.

## Core vs Downstream Boundary

- Core responsibilities:
  - Provide immutable published revisions and version metadata.
  - Preserve lifecycle history for replay.
- Downstream responsibilities:
  - Build/rebuild index projections.
  - Operate cutover and rollback.
  - Monitor and validate result quality during migration.
- Why this boundary:
  - Reindex mechanics depend on downstream search backend and SLOs.

## Implementation Sketch

### Data Model

Create control tables:

- `downstream_kp_reindex_job`
  - `job_id UUID PRIMARY KEY`
  - `index_version TEXT NOT NULL`
  - `status TEXT NOT NULL`
  - `started_at timestamptz NOT NULL`
  - `completed_at timestamptz NULL`
- `downstream_kp_reindex_cursor`
  - `job_id UUID NOT NULL`
  - `last_revision_id UUID NULL`
  - `processed_count BIGINT NOT NULL`
  - primary key `(job_id)`

### Services / APIs

Runbook commands:
1. `start_reindex(index_version)`
2. `resume_reindex(job_id)`
3. `cutover_index(index_version)`
4. `rollback_index(previous_index_version)`

### Operational Notes

Standard procedure:
1. Create new index/projection target.
2. Backfill all currently published revisions.
3. Replay recent events from checkpoint gap window.
4. Run parity checks against active index.
5. Cut over read traffic.
6. Keep old index for rollback window.

## Validation

- Completeness checks: published revision counts match source-of-truth.
- Spot relevance checks on sampled high-volume queries.
- Latency checks before and after cutover.
- Rollback drill proving previous index can be restored quickly.

## Risks / Open Questions

- Long-running backfills increasing event lag.
- Large rollback windows increasing infrastructure cost.
- Coordination with product teams during cutover windows.
