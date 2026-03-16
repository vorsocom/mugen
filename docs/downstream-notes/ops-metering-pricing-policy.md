# Ops Metering Pricing Policy

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Core `ops_metering` produces generic measured/rated usage and billing usage events.
It intentionally does not implement product/tier pricing policy. Downstream code
must map generic usage (`billable_quantity`, meter code, account/subscription context)
into commercial pricing outcomes.

## Decision

- Keep pricing and package rules fully downstream.
- Treat `OpsRatedUsages` as normalized usage input, not final money output.
- Use downstream policy tables keyed by tenant + product/tier + meter code.
- Preserve a deterministic pricing trace reference on generated invoice lines.

## Core vs Downstream Boundary

- Core responsibilities:
  - Measure usage and apply generic caps/multipliers/rounding/window rules.
  - Produce `OpsRatedUsages` and billing `UsageEvents`.
- Downstream responsibilities:
  - Convert rated usage into currency amounts and invoice line strategies.
  - Implement package allowances, overage policy, and tier breakpoints.
  - Own pricing versioning and commercial rollout controls.
- Why this boundary:
  - Pricing semantics are business-specific and change independently of core.

## Implementation Sketch

### Data Model

Add downstream pricing policy tables, for example:

- `downstream_meter_pricing_policy`
  - `tenant_id UUID NOT NULL`
  - `meter_code CITEXT NOT NULL`
  - `product_code CITEXT NULL`
  - `tier_code CITEXT NULL`
  - `pricing_model CITEXT NOT NULL` (`flat/per_unit/tiered/package`)
  - `currency CITEXT NOT NULL`
  - `config JSONB NOT NULL`
  - `effective_from timestamptz NOT NULL`
  - `effective_to timestamptz NULL`
  - `is_active bool NOT NULL DEFAULT true`
- Unique active policy key on `(tenant_id, meter_code, product_code, tier_code, effective_from)`.

### Services / APIs

1. Read `OpsRatedUsages` rows not yet priced downstream.
2. Resolve effective pricing policy for each usage row.
3. Compute line amount deterministically and attach pricing trace metadata.
4. Create/update downstream billing line records linked by rated-usage id.

### Operational Notes

- Roll out policy changes with future `effective_from`.
- Keep policy resolution deterministic and replay-safe.
- Maintain a backfill command for repricing by time window.

## Validation

- Unit tests for each pricing model and boundary condition.
- Integration test: rated usage -> priced line with expected amount/currency.
- Replay test: same rated usage yields identical pricing output.

## Risks / Open Questions

- Handling retroactive policy changes on already issued invoices.
- Multi-currency fallback behavior when policy is missing.
- Partial migration strategy for legacy pricing models.
