# Ops Metering Billing Account Resolution

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

`ops_metering` supports usage ingestion with partial business context. Some records
may not include complete billing linkage (`account_id`, `subscription_id`, `price_id`)
at ingest time. Downstream logic must resolve missing billing identities before
financial processing.

## Decision

- Keep identity resolution logic downstream.
- Allow ingest with partial context, but require resolution before invoicing.
- Resolve using deterministic precedence rules and append resolution metadata.
- Fail closed (queue for review) when no unambiguous billing identity exists.

## Core vs Downstream Boundary

- Core responsibilities:
  - Store usage/rated records with optional billing foreign keys.
  - Preserve immutable usage and action audit trail.
- Downstream responsibilities:
  - Resolve account/subscription/price references from domain context.
  - Maintain mapping/projection tables for high-volume lookup.
  - Decide manual-review and exception workflow.
- Why this boundary:
  - Identity linkage is product/domain topology, not reusable core behavior.

## Implementation Sketch

### Data Model

Add downstream mapping/projection tables, for example:

- `downstream_metering_subject_billing_map`
  - `tenant_id UUID NOT NULL`
  - `subject_namespace CITEXT NOT NULL`
  - `subject_id UUID NULL`
  - `subject_ref CITEXT NULL`
  - `account_id UUID NOT NULL`
  - `subscription_id UUID NULL`
  - `price_id UUID NULL`
  - `is_active bool NOT NULL DEFAULT true`
- Indexes on `(tenant_id, subject_namespace, subject_id)` and
  `(tenant_id, subject_namespace, subject_ref)`.

### Services / APIs

1. Consume unrouted `OpsUsageRecords` / `OpsRatedUsages`.
2. Resolve billing identity via configured precedence:
   explicit id -> subject map -> default tenant account policy.
3. Persist resolved ids and downstream resolution trace fields.
4. Route unresolved rows into review queue.

### Operational Notes

- Build projection refresh jobs from source-of-truth domain entities.
- Include strict uniqueness checks on active mappings.
- Track resolution hit/miss metrics per tenant.

## Validation

- Unit tests for precedence and ambiguity rules.
- Integration test with partial-context usage ingest and successful resolution.
- Negative test for ambiguous mapping -> review queue.

## Risks / Open Questions

- Stale subject mappings during account migrations.
- Cross-tenant data safety checks for mapping writes.
- Manual resolution UX ownership and SLA.
