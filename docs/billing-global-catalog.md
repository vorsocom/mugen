# Billing Global Catalog

- Status: active
- Owner: core billing maintainers
- Last Updated: 2026-08-24

## Ownership and routes

`BillingProducts` and `BillingPrices` are global platform catalog resources:

```text
GET|POST /api/core/acp/v1/BillingProducts
GET|PATCH /api/core/acp/v1/BillingProducts/{productId}

GET|POST /api/core/acp/v1/BillingPrices
GET|PATCH /api/core/acp/v1/BillingPrices/{priceId}
```

Their payloads do not accept or return `TenantId`. Tenant-form routes for these
entity sets return `400` because ACP derives scope from the EDM shape.

Billing Accounts and Subscriptions remain tenant-owned:

```text
tenant Billing Account -> tenant Subscription -> global Price -> global Product
```

A Subscription create request uses the tenant route and global `PriceId`:

```http
POST /api/core/acp/v1/tenants/{tenantId}/BillingSubscriptions
```

```json
{
  "AccountId": "<tenant-account-uuid>",
  "PriceId": "<global-price-uuid>"
}
```

The service rejects an Account from another tenant, an archived Price or
Product, and invalid metering capability. Two tenants may reference the same
global Price.

## Permissions and lifecycle

The global `<billing-namespace>:catalog_reader` role receives `read` permission
for Products and Prices only. Catalog create, update, archive, and restore remain
administrator operations. Archive uses:

```text
POST /api/core/acp/v1/BillingProducts/{productId}/$action/archive
POST /api/core/acp/v1/BillingPrices/{priceId}/$action/archive
```

with a `RowVersion` payload. Restore uses ACP's standard global `$restore`
endpoint.

Collections return active catalog rows. Archived rows remain resolvable by
direct ID and through tenant-resource forward navigation so historical billing
records do not lose their Product or Price meaning. A global Price deliberately
has no reverse Subscription, Invoice Line, Usage Event, or Entitlement Bucket
navigation.

Archiving does not terminate or alter a current Subscription. It prevents new
Subscriptions and reactivation; existing current and historical references
remain readable.

## Catalog rules

- Codes are trimmed before persistence and use PostgreSQL `CITEXT` comparison.
- Product Code is unique across active and archived Products.
- Price Code is unique within Product across active and archived Prices.
- Restoring cannot become ambiguous through soft-deleted code reuse.
- `Attributes` is global, non-secret catalog metadata.

After any Billing or Ops Metering row references a Price, these commercial
fields are immutable: Product, Price Type, Currency, Unit Amount, interval,
trial period, Usage Unit, and Meter Code. Create a new Price for a commercial
change. Code and Attributes remain mutable.

## Meter contract

A Price represents at most one billing meter:

- `MeterCode` and `UsageUnit` are supplied together.
- A metered Price requires both.
- A non-metered Price may omit both.
- Subscription create or reactivation requires a matching active tenant
  `OpsMeterDefinition` for a metered Price.
- Meter Code comparison trims whitespace and is case-insensitive.
- Meter Definition Unit must match Price Usage Unit after the same
  normalization.

Several independently billed meters require a separate multi-meter model; one
Price binding must not be treated as satisfying several operational meters.

## Migration and downgrade

Revision `3e7c9a1b5d2f` performs the catalog consolidation transactionally while
holding write locks over the catalog and all rewritten references. It:

1. Rejects non-empty legacy catalog Attributes with row IDs and attribute keys.
2. Groups trimmed, case-insensitive Codes and rejects materially conflicting
   Products or Prices.
3. Selects the earliest `CreatedAt`, then lowest ID, as the canonical row.
4. Rewrites four Core Billing foreign keys and three Ops Metering denormalized
   Price references.
5. Removes Product and Price tenant ownership and installs global constraints.
6. Validates every resulting Product and Price reference.

The migration retains legacy Product, Price, and Price-reference mapping tables
for downgrade. Downgrade restores exact legacy IDs and rows. It refuses to run
if post-upgrade catalog or Price-reference mutations would make exact recovery
unsafe. PostgreSQL transactional DDL rolls back all migration work on a conflict
or validation failure.

## Downstream changes

Downstream applications must remove tenant filters from Product and Price
lookups while retaining tenant filters for Accounts and Subscriptions. Each
application seeds its global Product/Price catalog records and updates
entitlement/readiness integrations. Multi-meter requirements remain a separate
design decision.
