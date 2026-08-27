"""
Billing plugin contribution entrypoint.

This module contributes *billing* artifacts into the ACP `IAdminRegistry` so they
are automatically exposed in the Admin Control Plane via ACP's generic CRUD/action
endpoints and are included in ACP seeding manifests.

Key design choices
------------------
- **Permission types (verbs)** are owned by ACP and live under `admin_namespace`.
  This contributor reuses those verbs:
  (":read", ":create", ":update", ":delete", ":manage")
  and does **not** re-register them.

- **Permission objects (nouns)** are owned by the billing plugin and live under
  `plugin_namespace`. Each billing resource registers a corresponding permission object:
      "<plugin_namespace>:account", "<plugin_namespace>:invoice", ...

- **Default grants**: the ACP administrator global role
      "<admin_namespace>:administrator"
  receives broad permissions over all billing objects by default.

- **Service keys** follow ACP convention:
      "<admin_namespace>:<edm_type_name>"
  so the AdminRuntimeBinder can create and register services uniformly.

Purity / migration safety
-------------------------
This module is safe to import/execute under Alembic because it:
- does not import framework code (Quart/FastAPI),
- does not access global application state,
- only registers declarative metadata and runtime binding specs.

"""

import re
from typing import Any

from mugen.core.plugin.acp.contract.sdk.binding import (
    TableSpec,
    EdmTypeSpec,
    RelationalServiceSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    GlobalRoleDef,
    PermissionObjectDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminCapabilities,
    AdminBehavior,
    AdminPermissions,
    AdminResource,
    CrudPolicy,
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.api.validation import (
    BillingAccountCreateValidation,
    BillingAccountUpdateValidation,
    BillingAdjustmentCreateValidation,
    BillingAdjustmentUpdateValidation,
    BillingCreditNoteCreateValidation,
    BillingCreditNoteUpdateValidation,
    BillingDiscountDefinitionCreateValidation,
    BillingDiscountDefinitionUpdateValidation,
    BillingEntitlementAdjustValidation,
    BillingEntitlementBucketCreateValidation,
    BillingEntitlementBucketUpdateValidation,
    BillingInvoiceCreateValidation,
    BillingInvoiceTemplateCreateValidation,
    BillingInvoiceTemplateUpdateValidation,
    BillingInvoiceLineCreateValidation,
    BillingInvoiceLineUpdateValidation,
    BillingInvoiceUpdateValidation,
    BillingLedgerEntryCreateValidation,
    BillingMeterDefinitionCreateValidation,
    BillingMeterDefinitionUpdateValidation,
    BillingPaymentAllocationCreateValidation,
    BillingPaymentCreateValidation,
    BillingPaymentTermCreateValidation,
    BillingPaymentTermUpdateValidation,
    BillingPaymentUpdateValidation,
    BillingPriceCreateValidation,
    BillingPriceEntitlementCreateValidation,
    BillingPriceEntitlementUpdateValidation,
    BillingPriceUpdateValidation,
    BillingProductCreateValidation,
    BillingProductUpdateValidation,
    BillingRunCreateValidation,
    BillingRunDefinitionCreateValidation,
    BillingRunDefinitionUpdateValidation,
    BillingRunFailValidation,
    BillingRunRetryValidation,
    BillingRunUpdateValidation,
    BillingSubscriptionCreateValidation,
    BillingSubscriptionPeriodValidation,
    BillingSubscriptionUpdateValidation,
    BillingTaxCodeCreateValidation,
    BillingTaxCodeUpdateValidation,
    BillingTaxRateCreateValidation,
    BillingTaxRateUpdateValidation,
    BillingUsageAllocationCreateValidation,
    BillingUsageEventCreateValidation,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+")


def _humanize(s: str) -> str:
    """Convert PascalCase/camelCase identifiers into a display title."""
    return " ".join(_WORD_RE.findall(s)).strip()


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """
    Contribute billing resources into the ACP registry.

    Parameters
    ----------
    registry:
        Mutable ACP registry instance (must not be frozen).

    admin_namespace:
        ACP namespace (verbs + service key prefix).

    plugin_namespace:
        Billing plugin namespace (permission objects + system flags).
    """
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    # ------------------------------------------------------------------
    # 1) System flags (plugin-owned)
    # ------------------------------------------------------------------
    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Billing plugin installed.",
            is_set=True,
        )
    )
    registry.register_global_role(
        GlobalRoleDef(
            namespace=plugin_ns.ns,
            name="catalog_reader",
            display_name="Billing Catalog Reader",
        )
    )

    # ------------------------------------------------------------------
    # 2) Resource catalog
    # ------------------------------------------------------------------
    # NOTE: ACP's generic DELETE endpoint is currently a hard delete. For safety,
    # billing resources default to allow_delete=False.
    lifecycle_actions = {
        "activate": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Activate this global billing definition?",
            "is_admin_action": True,
        },
        "deactivate": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Deactivate this global billing definition?",
            "is_admin_action": True,
        },
    }
    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "BillingAccounts",
            "entity": "Account",
            "description": "Billing customer/account record (tenant-scoped).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingAccountCreateValidation,
                update_schema=BillingAccountUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
        },
        {
            "set": "BillingProducts",
            "entity": "Product",
            "description": "Global billable product or platform SKU.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingProductCreateValidation,
                update_schema=BillingProductUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_deleted_collection_views=True,
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "resolve_soft_deleted_references": True,
            "actions": {
                "archive": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Archive this global product?",
                    "is_admin_action": True,
                },
            },
        },
        {
            "set": "BillingPrices",
            "entity": "Price",
            "description": (
                "Global Price definition for a Product " "(one-time/recurring/metered)."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingPriceCreateValidation,
                update_schema=BillingPriceUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_deleted_collection_views=True,
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "resolve_soft_deleted_references": True,
            "actions": {
                "archive": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Archive this global price?",
                    "is_admin_action": True,
                },
            },
        },
        {
            "set": "BillingMeterDefinitions",
            "entity": "MeterDefinition",
            "description": "Canonical global usage-meter definitions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingMeterDefinitionCreateValidation,
                update_schema=BillingMeterDefinitionUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingPriceEntitlements",
            "entity": "PriceEntitlement",
            "description": "Global included-usage rules owned by recurring Prices.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingPriceEntitlementCreateValidation,
                update_schema=BillingPriceEntitlementUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_deleted_collection_views=True,
                allow_restore=False,
                allow_hard_delete=False,
            ),
            "resolve_soft_deleted_references": True,
            "actions": {
                "archive": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Archive this unused Price entitlement rule?",
                    "is_admin_action": True,
                },
            },
        },
        {
            "set": "BillingRunDefinitions",
            "entity": "RunDefinition",
            "description": "Reusable global billing-run cadence definitions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingRunDefinitionCreateValidation,
                update_schema=BillingRunDefinitionUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingCurrencyDefinitions",
            "entity": "CurrencyDefinition",
            "description": "Vendored ISO 4217 currencies supported by the platform.",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingTaxCodes",
            "entity": "TaxCode",
            "description": "Reusable global tax classifications.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingTaxCodeCreateValidation,
                update_schema=BillingTaxCodeUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingTaxRates",
            "entity": "TaxRate",
            "description": "Effective-dated global tax rates.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingTaxRateCreateValidation,
                update_schema=BillingTaxRateUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingPaymentTerms",
            "entity": "PaymentTerm",
            "description": "Reusable global payment-term definitions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingPaymentTermCreateValidation,
                update_schema=BillingPaymentTermUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingInvoiceTemplates",
            "entity": "InvoiceTemplate",
            "description": "Reusable global invoice template definitions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingInvoiceTemplateCreateValidation,
                update_schema=BillingInvoiceTemplateUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingDiscountDefinitions",
            "entity": "DiscountDefinition",
            "description": "Reusable global discount and coupon definitions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "provider_module": "catalog",
            "crud": CrudPolicy(
                create_schema=BillingDiscountDefinitionCreateValidation,
                update_schema=BillingDiscountDefinitionUpdateValidation,
            ),
            "actions": lifecycle_actions,
        },
        {
            "set": "BillingSubscriptions",
            "entity": "Subscription",
            "description": (
                "Subscription binding an account to a price (tenant-scoped)."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingSubscriptionCreateValidation,
                update_schema=BillingSubscriptionUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "actions": {
                "cancel": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Cancel this subscription?",
                },
                "reactivate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Reactivate this subscription?",
                },
                "advance_period": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BillingSubscriptionPeriodValidation,
                    "confirm": "Open the next Subscription period?",
                },
                "reconcile_entitlements": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BillingSubscriptionPeriodValidation,
                    "confirm": "Reconcile missing current-period entitlements?",
                },
            },
        },
        {
            "set": "BillingRuns",
            "entity": "BillingRun",
            "table_name": "billing_run",
            "description": (
                "Idempotent period-processing run ledger for recurring billing"
                " workflows."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingRunCreateValidation,
                update_schema=BillingRunUpdateValidation,
            ),
            "actions": {
                "start": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Start this Billing Run?",
                },
                "complete": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Complete this Billing Run?",
                },
                "fail": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BillingRunFailValidation,
                    "confirm": "Mark this Billing Run failed?",
                },
                "cancel": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Cancel this Billing Run?",
                },
                "retry": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BillingRunRetryValidation,
                    "confirm": "Create a retry attempt?",
                },
                "reconcile_entitlements": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Reconcile this Billing Run's entitlement buckets?",
                },
            },
        },
        {
            "set": "BillingUsageEvents",
            "entity": "UsageEvent",
            "description": "Usage/meter events used for metered billing (append-only).",
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingUsageEventCreateValidation,
            ),
        },
        {
            "set": "BillingEntitlementBuckets",
            "entity": "EntitlementBucket",
            "description": (
                "Included-usage entitlement pools by account/subscription and period"
                " (tenant-scoped)."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(),
            "actions": {
                "adjust": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BillingEntitlementAdjustValidation,
                    "confirm": "Apply this audited entitlement adjustment?",
                },
            },
        },
        {
            "set": "BillingEntitlementAdjustments",
            "entity": "EntitlementAdjustment",
            "description": "Append-only audited entitlement capacity adjustments.",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "BillingUsageAllocations",
            "entity": "UsageAllocation",
            "description": (
                "Links usage events to entitlement buckets for included-usage"
                " accounting (append-only, tenant-scoped)."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingUsageAllocationCreateValidation,
            ),
        },
        {
            "set": "BillingInvoices",
            "entity": "Invoice",
            "description": "Invoice header record (tenant-scoped).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingInvoiceCreateValidation,
                update_schema=BillingInvoiceUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "actions": {
                "issue": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Issue this invoice?",
                },
                "void": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Void this invoice?",
                },
                "mark_paid": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Mark this invoice as paid?",
                },
            },
        },
        {
            "set": "BillingCreditNotes",
            "entity": "CreditNote",
            "description": "Credit notes used to correct issued invoice totals.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingCreditNoteCreateValidation,
                update_schema=BillingCreditNoteUpdateValidation,
            ),
        },
        {
            "set": "BillingAdjustments",
            "entity": "Adjustment",
            "description": "Generic debit/credit adjustments for billing corrections.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingAdjustmentCreateValidation,
                update_schema=BillingAdjustmentUpdateValidation,
            ),
        },
        {
            "set": "BillingInvoiceLines",
            "entity": "InvoiceLine",
            "description": "Invoice line items (tenant-scoped).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingInvoiceLineCreateValidation,
                update_schema=BillingInvoiceLineUpdateValidation,
            ),
        },
        {
            "set": "BillingPayments",
            "entity": "Payment",
            "description": "Payments and payment attempts (tenant-scoped).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingPaymentCreateValidation,
                update_schema=BillingPaymentUpdateValidation,
            ),
        },
        {
            "set": "BillingPaymentAllocations",
            "entity": "PaymentAllocation",
            "description": (
                "Allocation records linking payments to invoices"
                " (append-only, tenant-scoped)."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=BillingPaymentAllocationCreateValidation,
            ),
            "actions": {
                "sync_invoice": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Recompute invoice totals and status from allocations?",
                }
            },
        },
        {
            "set": "BillingLedgerEntries",
            "entity": "LedgerEntry",
            "description": "Accounting ledger entries (append-only, tenant-scoped).",
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=BillingLedgerEntryCreateValidation,
            ),
        },
    )

    # ------------------------------------------------------------------
    # 3) Permission objects (plugin-owned nouns)
    # ------------------------------------------------------------------
    billing_objects: list[PermissionObjectDef] = []
    for r in resources:
        obj_name = title_to_snake(r["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        billing_objects.append(obj)
        registry.register_permission_object(obj)

    # ------------------------------------------------------------------
    # 4) Default grants (bootstrap policy)
    # ------------------------------------------------------------------
    billing_obj_keys = [o.key for o in billing_objects]
    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in billing_obj_keys
        for ptyp in admin_verb_keys
    )
    catalog_object_keys = {
        PermissionObjectDef(plugin_ns.ns, title_to_snake(resource["entity"])).key
        for resource in resources
        if resource["set"]
        in {
            "BillingCurrencyDefinitions",
            "BillingDiscountDefinitions",
            "BillingInvoiceTemplates",
            "BillingMeterDefinitions",
            "BillingPaymentTerms",
            "BillingPriceEntitlements",
            "BillingPrices",
            "BillingProducts",
            "BillingRunDefinitions",
            "BillingTaxCodes",
            "BillingTaxRates",
        }
    }
    registry.register_default_global_grants(
        DefaultGlobalGrant(
            plugin_ns.key("catalog_reader"),
            permission_object,
            admin_ns.verb("read"),
            True,
        )
        for permission_object in sorted(catalog_object_keys)
    )

    # ------------------------------------------------------------------
    # 5) AdminResources + declarative runtime binding specs
    # ------------------------------------------------------------------
    for r in resources:
        entity_set = r["set"]
        entity = r["entity"]

        obj_name = title_to_snake(entity)
        provider_module = str(r.get("provider_module", obj_name))
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"BILLING.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"billing_{obj_name}"))

        registry.register_resource(
            AdminResource(
                namespace=plugin_ns.ns,
                entity_set=entity_set,
                edm_type_name=edm_type_name,
                perm_obj=pobj.key,
                service_key=service_key,
                permissions=AdminPermissions(
                    permission_object=pobj.key,
                    read=admin_ns.verb("read"),
                    create=admin_ns.verb("create"),
                    update=admin_ns.verb("update"),
                    delete=admin_ns.verb("delete"),
                    manage=admin_ns.verb("manage"),
                ),
                capabilities=AdminCapabilities(
                    allow_read=bool(r.get("allow_read", True)),
                    allow_create=bool(r.get("allow_create", False)),
                    allow_update=bool(r.get("allow_update", False)),
                    allow_delete=bool(r.get("allow_delete", False)),
                    allow_manage=bool(r.get("allow_manage", False)),
                    actions=dict(r.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    soft_delete=r.get("soft_delete", SoftDeletePolicy()),
                    rgql_enabled=True,
                    resolve_soft_deleted_references=bool(
                        r.get("resolve_soft_deleted_references", False)
                    ),
                ),
                crud=r.get("crud", CrudPolicy()),
                title=_humanize(entity_set),
                description=r["description"],
            )
        )

        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=(
                    f"mugen.core.plugin.billing.model.{provider_module}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=("mugen.core.plugin.billing.edm:" f"{obj_name}_type"),
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.billing.service."
                    f"{provider_module}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
