"""Provides a CRUD service for billing accounts."""

__all__ = ["AccountService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.account import IAccountService
from mugen.core.plugin.billing.domain import AccountDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class AccountService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[AccountDE],
    IAccountService,
):
    """A CRUD service for billing accounts."""

    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
        "tax_code_id": ("billing_tax_code", "TaxCodeId"),
        "payment_term_id": ("billing_payment_term", "PaymentTermId"),
        "invoice_template_id": ("billing_invoice_template", "InvoiceTemplateId"),
        "discount_definition_id": (
            "billing_discount_definition",
            "DiscountDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AccountDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
