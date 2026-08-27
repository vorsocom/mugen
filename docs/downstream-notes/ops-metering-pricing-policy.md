# Ops Metering Pricing Policy

- Status: active
- Owner: core billing and downstream plugin teams
- Last Updated: 2026-08-27

## Context

Core owns canonical global meter semantics and the included quantities advertised
by global package Prices. `ops_metering` produces generic measured/rated usage and
Billing turns Price Entitlement rules into tenant period buckets. Downstream code
still owns business-specific overage pricing, tier breaks, and invoice-line
strategy.

## Core contract

- `BillingMeterDefinitions` owns globally stable Code, Unit, and Aggregation Mode.
- Ops Metering Policies, Sessions, Records, and Rated Usage use
  `MeterDefinitionId`; they do not create tenant meter semantics.
- `BillingPrices` uses `MeterDefinitionId` for metered prices and retains Code/Unit
  snapshots for compatibility.
- `BillingPriceEntitlements` is the authoritative package allowance contract.
- Subscription/Billing Run workflows generate tenant Entitlement Buckets exactly
  once per rule and period.
- `OpsRatedUsages` remains normalized usage input, not final money output.

## Downstream responsibilities

- Resolve effective overage or tiering policy by tenant, Price, and canonical
  Meter Definition.
- Convert rated usage beyond Core entitlements into currency amounts and invoice
  line strategies.
- Preserve a deterministic pricing trace reference on generated invoice lines.
- Version business-specific policy with effective windows and make replay and
  reconciliation deterministic.

Downstream policy must not redefine the meter Unit/Aggregation Mode or duplicate
the package included quantity in an independent authority. A downstream table may
key policy by `(tenant_id, price_id, meter_definition_id, effective_from)` and
store only the additional pricing behavior it owns.

## Processing outline

1. Read unprocessed `OpsRatedUsages` and their canonical meter IDs.
2. Resolve the Subscription, Price, and current tenant Entitlement Bucket.
3. Allocate included usage through Core Billing.
4. Apply the effective downstream policy to any billable remainder.
5. Create invoice-line data with Price, Meter Definition, and deterministic
   pricing-trace provenance.

## Validation

- Test each pricing model and effective-window boundary.
- Verify package allowance is taken from generated Core buckets.
- Verify two tenants can use the same Price/meter while applying distinct allowed
  overage policies.
- Verify replay produces the same allocation and financial result.
- Verify historical invoices do not change after catalog or downstream policy
  revisions.

## Compatibility

Legacy tenant `OpsMeterDefinitions` is read-only and deprecated. Consumers should
read `BillingMeterDefinitions` globally and migrate stored legacy IDs through the
canonical mapping established by the migration.
