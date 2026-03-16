"""Provides a service contract for PaymentDE-related services."""

__all__ = ["IPaymentService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import PaymentDE


class IPaymentService(
    ICrudService[PaymentDE],
    ABC,
):
    """A service contract for PaymentDE-related services."""
