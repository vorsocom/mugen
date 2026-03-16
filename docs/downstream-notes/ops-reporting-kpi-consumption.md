# Ops Reporting KPI Consumption

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

`ops_reporting` in core provides generic metric definitions, deterministic
aggregation, and report snapshot lifecycle. It intentionally does not include
dashboard UX, business KPI semantics, or domain-specific ranking/threshold
policy behavior. Downstream plugins need a clear pattern for:

- defining KPI meaning per business domain,
- turning generic metric/snapshot outputs into product workflows,
- validating CRUD/actions using reusable HTTP E2E specs.

## Decision

- Keep `ops_reporting` core resources generic and reusable across domains.
- Define KPI semantics, views, and rollout logic in downstream plugins/apps.
- Use downstream-owned projection/serving layers for dashboards and read APIs.
- Treat ACP HTTP E2E JSON specs as test assets under `mugen_test`, not docs.

## Core vs Downstream Boundary

- Core responsibilities:
  - Generic entities:
    `MetricDefinition`, `MetricSeries`, `AggregationJob`,
    `ReportDefinition`, `ReportSnapshot`, `KpiThreshold`.
  - Deterministic/idempotent aggregation behavior for metric/window/scope.
  - Generic snapshot lifecycle actions:
    `generate_snapshot`, `publish_snapshot`, `archive_snapshot`.
  - ACP CRUD/action exposure and authorization primitives.
- Downstream responsibilities:
  - KPI catalogs and ownership (which metrics matter for each domain).
  - UI and API contracts for dashboards, scorecards, and executive summaries.
  - Domain-specific threshold semantics (alerts, escalation policy, paging).
  - Backfill cadence, SLO interpretation, and run orchestration policy.
- Why this boundary:
  - KPI meaning changes per domain and evolves faster than core contracts.
  - Keeping semantics downstream avoids locking core to one reporting model.

## Implementation Sketch

### Data Model

Use core `ops_reporting` tables directly for generic aggregation state.

If needed, add downstream projection tables for read-optimized consumption, for
example:

- `downstream_kpi_view_cache`
  - denormalized metric bundles per tenant/window/scope
  - UI-focused fields (labels, trend arrows, color bands)
  - rebuildable from `ReportSnapshot.summary_json` + downstream metadata

Keep projection generation idempotent and keyed by
`(tenant_id, report_snapshot_id)` or equivalent natural key.

### Services / APIs

Downstream service flow:

1. Maintain downstream KPI catalog (maps product KPI names -> metric codes).
2. Trigger `run_aggregation` / `recompute_window` as part of domain jobs.
3. Trigger `generate_snapshot` then `publish_snapshot` for release windows.
4. Consume published snapshots into downstream read APIs/UI.
5. Optionally archive stale snapshots with `archive_snapshot`.

### Operational Notes

- Use explicit window contracts (UTC boundaries) to avoid timezone drift.
- Keep scope keys stable (`__all__` vs domain-specific scope partitioning).
- Prefer immutable published snapshots for auditability and reproducibility.
- Store any dashboard-only metadata downstream, not in core models.

## Validation

Core plugin behavior can be validated with ACP HTTP E2E specs now stored as
test assets:

- `mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-aggregation.template.json`
- `mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-snapshot.template.json`

Suggested run flow:

1. Copy template to `/tmp` and inject unique lookup values.
2. Run:
   `bash .codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh --spec <spec.json>`
3. Require success for:
   - metric-definition create + `run_aggregation` + `recompute_window`
   - snapshot create + `generate_snapshot` + `publish_snapshot` + `archive_snapshot`

## Risks / Open Questions

- Which downstream job owns aggregation cadence (hourly, daily, event-driven)?
- How should late-arriving source rows be handled per domain SLA?
- Should downstream enforce one published snapshot per report/window/scope?
- Which tenant-specific KPI catalogs require strict change management?
