# Ops Governance Enforcement Orchestration

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

`ops_governance` provides generic ACP resources for consent/delegation records,
policy definitions, policy decision logs, retention policies, and data handling
records. Core intentionally does not implement legal/business-specific policy
engines or enforcement workers.

Downstream plugins still need to execute real actions (redact/erase/notify/
route-to-review) and map them to domain objects. That orchestration belongs
outside core.

## Decision

- Keep `ops_governance` in core as metadata + immutable governance history.
- Implement enforcement workers and legal/business rules in downstream plugins.
- Treat `OpsPolicyDecisionLogs` and `OpsDataHandlingRecords` as the auditable
  control-plane ledger for downstream execution.
- Route downstream job outcomes back into `OpsDataHandlingRecords` status fields
  and rely on ACP audit events for request/action traceability.

## Core vs Downstream Boundary

- Core responsibilities:
  - CRUD/action surface for governance records through ACP.
  - Immutable history for consent/delegation and policy decisions.
  - Generic retention/action metadata and request tracking.
  - Audit emission through existing ACP + `audit` plugin integration.
- Downstream responsibilities:
  - Policy rule evaluation logic and legal interpretation.
  - Domain-specific target resolution (which records/files/messages to affect).
  - Execution jobs (redaction/erasure/export/notification) and retries.
  - SLA/alerting/reporting for compliance operations.
- Why this boundary:
  - Enforcement logic is jurisdiction- and product-specific, changes frequently,
    and should not hard-code into reusable core plugin contracts.

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

1. Read active `OpsRetentionPolicies` / `OpsPolicyDefinitions` for tenant scope.
2. For each apply/evaluate trigger, create/update downstream work item.
3. Worker resolves domain targets and executes concrete action.
4. Update `OpsDataHandlingRecords` (`RequestStatus`, `CompletedAt`,
   `ResolutionNote`, `HandledByUserId`, `Meta`) via ACP CRUD.
5. For policy evaluation outcomes, append entries through
   `evaluate_policy` action and treat `OpsPolicyDecisionLogs` as immutable
   evidence.

### Operational Notes

- Use idempotency keys tied to `DataHandlingRecordId` to avoid double execution.
- Prefer at-least-once queues with idempotent handlers over in-transaction work.
- Add periodic reconciler to requeue stale `in_progress` work items.
- Keep downstream target projections rebuildable from source-of-truth tables.

## Validation

- Unit tests:
  - rule-to-work-item mapping for each supported action type.
  - idempotent retry behavior per `data_handling_record_id`.
- Integration tests:
  - ACP action `apply_retention_action` -> downstream work item queued.
  - worker completion updates `OpsDataHandlingRecords` to `completed`.
  - worker failure updates status/retry metadata correctly.
- E2E checks:
  - include ACP HTTP action coverage (`evaluate_policy`,
    `apply_retention_action`) plus downstream worker run assertions.

## Risks / Open Questions

- Jurisdiction-specific retention semantics may require per-tenant policy packs.
- Large-domain target expansion may need batching and async fan-out controls.
- Downstream compensation strategy is needed for partial failures.
- Cross-plugin ownership of `target_namespace` conventions should be standardized.
