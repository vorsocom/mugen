"""Smoke tests for thin relational service constructor wrappers."""

import unittest

from mugen.core.plugin.acp.service.global_permission_entry import (
    GlobalPermissionEntryService,
)
from mugen.core.plugin.acp.service.global_role import GlobalRoleService
from mugen.core.plugin.acp.service.permission_entry import PermissionEntryService
from mugen.core.plugin.acp.service.permission_object import PermissionObjectService
from mugen.core.plugin.acp.service.permission_type import PermissionTypeService
from mugen.core.plugin.acp.service.person import PersonService
from mugen.core.plugin.acp.service.role import RoleService
from mugen.core.plugin.acp.service.system_flag import SystemFlagService
from mugen.core.plugin.acp.service.tenant import TenantService
from mugen.core.plugin.acp.service.tenant_domain import TenantDomainService
from mugen.core.plugin.acp.service.tenant_invitation import TenantInvitationService
from mugen.core.plugin.acp.service.tenant_membership import TenantMembershipService
from mugen.core.plugin.billing.service.account import AccountService
from mugen.core.plugin.billing.service.adjustment import AdjustmentService
from mugen.core.plugin.billing.service.billing_run import BillingRunService
from mugen.core.plugin.billing.service.credit_note import CreditNoteService
from mugen.core.plugin.billing.service.entitlement_bucket import (
    EntitlementBucketService,
)
from mugen.core.plugin.billing.service.invoice_line import InvoiceLineService
from mugen.core.plugin.billing.service.ledger_entry import LedgerEntryService
from mugen.core.plugin.billing.service.payment import PaymentService
from mugen.core.plugin.billing.service.price import PriceService
from mugen.core.plugin.billing.service.product import ProductService
from mugen.core.plugin.billing.service.usage_allocation import UsageAllocationService
from mugen.core.plugin.context_engine.service.admin_resource import (
    ContextContributorBindingService,
    ContextPolicyService,
    ContextProfileService,
    ContextSourceBindingService,
    ContextTracePolicyService,
)
from mugen.core.plugin.context_engine.service.runtime import (
    ContextCacheRecordService,
    ContextCommitLedgerService,
    ContextEventLogService,
    ContextMemoryRecordService,
    ContextStateSnapshotService,
    ContextTraceService,
)


class TestMugenRelationalServiceCtorSmoke(unittest.TestCase):
    """Ensures wrapper constructors wire table/rsg through base service init."""

    def test_ctor_smoke_for_thin_services(self) -> None:
        rsg = object()
        ctor_types = [
            GlobalPermissionEntryService,
            GlobalRoleService,
            PermissionEntryService,
            PermissionObjectService,
            PermissionTypeService,
            PersonService,
            RoleService,
            SystemFlagService,
            TenantService,
            TenantDomainService,
            TenantInvitationService,
            TenantMembershipService,
            AccountService,
            AdjustmentService,
            BillingRunService,
            CreditNoteService,
            EntitlementBucketService,
            InvoiceLineService,
            LedgerEntryService,
            PaymentService,
            PriceService,
            ProductService,
            UsageAllocationService,
            ContextProfileService,
            ContextPolicyService,
            ContextContributorBindingService,
            ContextSourceBindingService,
            ContextTracePolicyService,
            ContextStateSnapshotService,
            ContextEventLogService,
            ContextMemoryRecordService,
            ContextCacheRecordService,
            ContextCommitLedgerService,
            ContextTraceService,
        ]

        for idx, ctor in enumerate(ctor_types, start=1):
            instance = ctor(table=f"table_{idx}", rsg=rsg)
            self.assertEqual(instance.table, f"table_{idx}")
