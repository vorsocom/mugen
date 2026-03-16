# Ops Governance Enforcement Orchestration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-25

## Context

`ops_governance` now includes a core PDP for `OpsPolicyDefinitions` with
`dsl` document evaluation, decision outcomes (`allow/deny/warn/review`), and
obligation emission into immutable decision logs.

Downstream plugins still need to execute domain side effects (redact/erase/
notify/route-to-review) and map policy obligations onto business objects and
workers. That orchestration remains outside core.

## Decision

- Keep `ops_governance` in core for policy definition versioning, PDP
  evaluation, and immutable governance history.
- Keep non-approval obligation execution in downstream workers.
- Treat `OpsPolicyDecisionLogs` and `OpsDataHandlingRecords` as the auditable
  control-plane ledger for downstream execution and replay safety.
- Route downstream job outcomes back into `OpsDataHandlingRecords` status fields
  and rely on ACP audit events for request/action traceability.

## Core vs Downstream Boundary

- Core responsibilities:
  - CRUD/action surface for governance records through ACP.
  - Immutable history for consent/delegation and policy decisions.
  - `evaluate_policy` PDP execution on policy `DocumentJson` with obligation
    pass-through.
  - `activate_version` action enforcement for single active policy version per
    `(tenant, code)`.
  - Generic retention/action metadata and request tracking.
  - Audit emission through existing ACP + `audit` plugin integration.
- Downstream responsibilities:
  - Policy document authoring lifecycle (promotion/review) per tenant/product.
  - Domain-specific target resolution (which records/files/messages to affect).
  - Execution jobs (redaction/erasure/export/notification) and retries for
    obligations not enforced directly in core workflow paths.
  - SLA/alerting/reporting for compliance operations.
- Why this boundary:
  - Core PDP ensures deterministic decision logging, while obligation side
    effects stay jurisdiction- and product-specific.

## Implementation Sketch

### Data Model

Add downstream operational tables, for example:

- `downstream_ops_gov_work_item`
  - `tenant_id UUID NOT NULL`
  - `data_handling_record_id UUID NOT NULL`
  - `policy_definition_id UUID NULL`
  - `target_namespace CITEXT NOT NULL`
  - `target_ref CITEXT NULL`
  - `status CITEXT NOT NULL` (`queued/running/completed/failed/dead_letter`)
  - `attempt_count BIGINT NOT NULL DEFAULT 0`
  - `next_retry_at timestamptz NULL`
  - `last_error TEXT NULL`
  - `created_at/updated_at`
- `downstream_ops_gov_target_projection`
  - materialized target list keyed by tenant + domain identity used by workers.

Indexes:

- `BTREE (tenant_id, status, next_retry_at)` on work items.
- Unique `(tenant_id, data_handling_record_id)` for idempotent scheduling.
- Projection indexes matching downstream domain lookup paths.

### Services / APIs

Recommended downstream flow:

1. Manage policy document versions in `OpsPolicyDefinitions` and activate one
   version per policy code.
2. Call `evaluate_policy` with `InputJson` and optional `ActorJson`/`TraceId`.
3. Use returned obligations to schedule downstream side-effect work.
4. Worker resolves domain targets and executes concrete action.
5. Update `OpsDataHandlingRecords` (`RequestStatus`, `CompletedAt`,
   `ResolutionNote`, `HandledByUserId`, `Meta`) via ACP CRUD.
6. Treat `OpsPolicyDecisionLogs` as immutable evidence for audit and
   investigations.

### Operational Notes

- Use idempotency keys tied to `DataHandlingRecordId` to avoid double execution.
- Prefer at-least-once queues with idempotent handlers over in-transaction work.
- Add periodic reconciler to requeue stale `in_progress` work items.
- Keep downstream target projections rebuildable from source-of-truth tables.

## Validation

- Unit tests:
  - policy document version activation and single-active constraints.
  - rule-to-work-item mapping for each downstream obligation type.
  - idempotent retry behavior per `data_handling_record_id`.
- Integration tests:
  - ACP action `evaluate_policy` -> obligation fan-out -> downstream work item
    queued.
  - ACP action `apply_retention_action` -> downstream work item queued.
  - worker completion updates `OpsDataHandlingRecords` to `completed`.
  - worker failure updates status/retry metadata correctly.
- E2E checks:
  - include ACP HTTP action coverage (`evaluate_policy`,
    `activate_version`, `apply_retention_action`) plus downstream worker run
    assertions.

## Risks / Open Questions

- Weak policy document governance can drift obligations from legal intent.
- Jurisdiction-specific retention semantics may require per-tenant policy packs.
- Large-domain target expansion may need batching and async fan-out controls.
- Downstream compensation strategy is needed for partial failures.
- Cross-plugin ownership of `target_namespace` conventions should be standardized.
