# ACP Derivatives Orchestration Matrix

Status: Draft
Last Updated: 2026-02-14
Audience: Core and downstream plugin teams

## Context

Downstream teams need one planning artifact that summarizes ACP plus ACP-derived
core plugins, what each plugin owns, and what must remain downstream per
business case.

## Decision

Use this matrix as the first step when designing orchestration for new business
cases:

- identify which core plugins provide reusable primitives,
- keep policy and vertical execution logic downstream,
- compose across plugins through ACP resources/actions.

## Core vs Downstream Boundary

- Core responsibilities:
  - expose generic, reusable operational resources and actions via ACP,
  - maintain tenant-scoped state, lifecycle integrity, and auditability,
  - avoid embedding vertical product semantics in core.
- Downstream responsibilities:
  - define business policy and decision rules,
  - implement domain-specific workers, adapters, and UX,
  - orchestrate cross-plugin flows for specific product outcomes.
- Why this boundary:
  - maximizes core reusability,
  - prevents platform forks,
  - keeps vertical iteration fast.

## Implementation Sketch

### Data Model

Use ACP/core plugin schemas as system-of-record operational primitives.
Only add downstream projections for read optimization, policy materialization,
or execution state that is business-specific.

### Services / APIs

| Plugin | Core Primitive Scope | Downstream Ownership Focus |
| --- | --- | --- |
| `acp` | Tenant-scoped CRUD/action surface, permissions, resource registration/runtime binding | Business orchestration composition, app-level policy and operator UX |
| `audit` | Append-only write/action event ledger for ACP surfaces | Out-of-band write capture, retention/redaction operations, compliance reporting |
| `billing` | Account/product/price/subscription/usage/invoice/payment primitives | Product packaging, billing policy, reconciliation workflows, customer-facing finance UX |
| `channel_orchestration` | Intake/routing/throttle/blocklist/fallback controls and event timeline | Channel adapters, sender normalization, route/escalation policy, webhook/session handling |
| `knowledge_pack` | Knowledge pack/version lifecycle and publication metadata | Retrieval/ranking/redaction policy, search projections, channel-specific answer contracts |
| `ops_case` | Case lifecycle, assignment, escalation, and timeline primitives | Domain routing/ownership policy, case enrichment, external integration workflows |
| `ops_governance` | Consent/delegation/policy/retention metadata and actions | Jurisdiction-specific rule engines, enforcement workers, legal/compliance operations |
| `ops_metering` | Usage definitions, sessions, records, and rating-ready primitives | Identity resolution, pricing policy joins, replay/backfill/reconciliation operations |
| `ops_reporting` | Metric definitions, aggregation, report snapshots, publication lifecycle | KPI semantics, dashboards, consumer APIs, thresholding/escalation behavior |
| `ops_sla` | Business-hour-aware clocks and breach markers | SLA target policy, escalation ownership, notification/queue workflows |
| `ops_vpn` | Vendor registry/lifecycle and performance scorecard primitives | Vendor selection strategy, domain score models, procurement/execution integration |
| `ops_workflow` | Workflow definition/instance/task/approval primitives | Approval rules, actor eligibility, subject projections, orchestration of domain actions |

### Operational Notes

- Keep cross-plugin correlation identifiers stable across flows.
- Prefer ACP actions over direct table writes for lifecycle transitions.
- Model downstream automation as policy overlays, not schema forks.
- Treat this matrix as planning input; plugin-specific notes remain source of
  implementation detail.

## Validation

- Planning review:
  - map each business use case to plugin rows in this matrix,
  - explicitly document downstream-owned policy/execution per row.
- Technical checks for implementation changes:
  - `acp-python-style`
  - `alembic-migration-checker`
  - `acp-http-e2e-tester`

## Risks / Open Questions

- Some business flows may require cross-plugin compensation patterns not yet
  standardized.
- Plugin ownership boundaries can drift without periodic architecture review.
- Additional matrix columns may be useful later (SLO owner, event contracts,
  compliance tier).
