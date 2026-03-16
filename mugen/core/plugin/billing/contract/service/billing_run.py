"""Provides a service contract for BillingRunDE-related services."""

__all__ = ["IBillingRunService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import BillingRunDE


class IBillingRunService(
    ICrudService[BillingRunDE],
    ABC,
):
    """A service contract for BillingRunDE-related services."""
