# Core Platform Unified User Story

Status: Draft
Last Updated: 2026-02-14
Audience: Core and downstream plugin teams

## Context

muGen now includes a broad set of generic core plugins:

- `audit`
- `billing`
- `channel_orchestration`
- `knowledge_pack`
- `ops_case`
- `ops_governance`
- `ops_metering`
- `ops_reporting`
- `ops_sla`
- `ops_vpn`
- `ops_workflow`

These core implementations intentionally provide reusable primitives, not
vertical product behavior. We need one shared user story that aligns cross-plugin
intent and downstream ownership.

## Decision

Use a single platform user story to guide implementation and validation:

As an operations platform owner, I want muGen core plugins to provide generic,
auditable, policy-aware operational building blocks across intake, case handling,
workflow execution, SLA tracking, metering, billing, governance, knowledge
management, vendor performance, and reporting, so downstream plugins can deliver
vertical business outcomes without re-implementing foundational infrastructure.

## Core vs Downstream Boundary

- Core responsibilities:
  - `audit`: append-only system audit records for ACP writes/actions.
  - `billing`: products/prices/subscriptions/usage events/invoice and payment
    primitives for financial settlement.
  - `channel_orchestration`: generic intake/routing/throttle/blocklist/fallback.
  - `knowledge_pack`: approved-response versioning and publication controls.
  - `ops_case`: canonical case lifecycle, assignment, escalation, timeline.
  - `ops_governance`: consent/delegation/policy/retention metadata actions.
  - `ops_metering`: normalized usage capture/rating primitives.
  - `ops_reporting`: deterministic aggregation and snapshot lifecycle.
  - `ops_sla`: business-hour-aware clocks and breach markers.
  - `ops_vpn`: vendor registry, lifecycle, scorecard rollup primitives.
  - `ops_workflow`: bounded transitions, approvals, tasks, event trail.
- Downstream responsibilities:
  - Domain-specific decision rules and orchestration policy.
  - Product semantics (SOPs, routing heuristics, escalation policy, pricing).
  - Vertical UX, integrations, and enforcement workers.
  - KPI interpretation and customer-facing report contracts.
- Why this boundary:
  - Keeps core stable and reusable.
  - Enables faster vertical iteration without forking platform primitives.

## Implementation Sketch

### Data Model

- Treat core plugin schemas as canonical operational primitives.
- Add downstream projection tables only for read optimization or vertical views.
- Keep cross-plugin references explicit at downstream boundaries (for example,
  map `ops_case` + `ops_sla` + `ops_workflow` via subject/ref metadata rather
  than hardcoding vertical coupling into core).

### Services / APIs

- Use ACP CRUD/actions as the shared control plane surface.
- Compose workflows across core plugins in downstream services (alphabetical
  plugin order; downstream policy defines runtime sequence):
  1. Audit trace (`audit`)
  2. Billing settlement (`billing`)
  3. Intake/routing (`channel_orchestration`)
  4. Knowledge retrieval constraints (`knowledge_pack`)
  5. Case progression (`ops_case`)
  6. Governance checks (`ops_governance`)
  7. Usage capture (`ops_metering`)
  8. KPI output (`ops_reporting`)
  9. SLA tracking (`ops_sla`)
  10. Vendor execution and quality (`ops_vpn`)
  11. Task/approval flow (`ops_workflow`)

### Operational Notes

- Prefer immutable/append-only event records where defined by core plugin.
- Keep platform IDs and correlation metadata stable across plugin hops.
- Use deterministic status transitions and row-version concurrency paths from ACP.
- Treat downstream automation as policy overlays on top of core contracts.

## Validation

- Run full ACP HTTP E2E suite across all plugin templates:
  - `bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh`
- The suite validates core behavior across:
  - lifecycle and action dispatch (`ops_case`, `ops_sla`, `ops_vpn`)
  - CRUD + create-path guards (`knowledge_pack`, `ops_metering`, `ops_workflow`)
  - policy decision/action behavior (`ops_governance`)
  - aggregation/snapshot lifecycle (`ops_reporting`)
  - intake/routing/blocklist behavior (`channel_orchestration`)
- Billing is part of the unified platform story and should be validated with
  billing-focused migration/service/E2E checks as those specs are expanded.

## Risks / Open Questions

- Cross-plugin orchestration ownership (which downstream service is the source
  of truth for multi-plugin state transitions).
- Operational idempotency strategy across asynchronous downstream workers.
- Policy drift risk if downstream logic diverges from core generic assumptions.
- Need for additional E2E templates that cover richer multi-entity flows
  (for example workflow instance + task + approval end-to-end in one scenario).
