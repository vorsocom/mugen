# Billing Invoice Reconciliation Source Of Truth

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Invoice `amount_due`, `status`, and `paid_at` must stay consistent with payment
allocation mutations. Reconciliation logic appears in both migration SQL
artifacts and runtime service action paths. Downstream extensions must avoid
re-implementing this logic in additional Python code paths.

## Decision

- Canonicalize reconciliation in database function
  `mugen.fn_billing_sync_invoice_from_allocations(UUID, UUID)`.
- Treat the payment-allocation trigger
  `tr_billing_payment_allocation_sync_invoice` as automatic reconciliation for
  allocation writes.
- Keep ACP action `sync_invoice` as an explicit operator path that delegates to
  the same DB function.
- Apply reconciliation behavior changes through new migrations that update the
  function body.

## Core vs Downstream Boundary

- Core responsibilities:
  - Own SQL function and trigger definitions in migrations.
  - Expose operator-facing action (`sync_invoice`) through ACP service binding.
  - Keep function fixes forward-only (for example revision
    `c13f8d2a7b9e_fix_billing_sync_invoice_function`).
- Downstream responsibilities:
  - Invoke ACP action when manual re-sync is required.
  - Coordinate finance workflows around issued/paid/void state transitions.
  - Add monitoring/alerting around reconciliation failures and stale invoices.
- Why this boundary:
  - One reconciliation engine prevents drift between trigger-driven and
    action-driven flows.

## Implementation Sketch

### Data Model

Use existing billing tables and migration-owned DB routines:

- `billing_payment_allocation` changes trigger invoice sync.
- `billing_invoice` stores reconciled `amount_due`, `status`, `paid_at`.
- Function body currently defined in migration lineage including:
  - `f7b1c2d3e4a5_billing_runs_adjustments_and_meter_codes`
  - `c13f8d2a7b9e_fix_billing_sync_invoice_function`

### Services / APIs

1. Operator calls ACP action `sync_invoice` on `BillingPaymentAllocations`.
2. `PaymentAllocationService.action_sync_invoice` executes
   `SELECT mugen.fn_billing_sync_invoice_from_allocations(...)`.
3. Trigger path and action path converge in the same SQL function.

### Operational Notes

- Do not add secondary Python-side invoice total/status calculators.
- For reconciliation logic changes, ship migration SQL first, then verify ACP
  action still delegates to the same function signature.

## Validation

- Migration check: function exists after `upgrade head`.
- Integration checks:
  - allocation insert updates invoice due/status correctly,
  - allocation update that changes invoice target re-syncs affected invoices,
  - allocation delete re-syncs invoice.
- ACP action check: `sync_invoice` returns success and applies same results as
  trigger-driven updates.

## Risks / Open Questions

- Function and service can drift if signature or semantics change without
  coordinated migration and service updates.
- Concurrent allocation writes can still require tenant-level operational
  observability for troubleshooting.
