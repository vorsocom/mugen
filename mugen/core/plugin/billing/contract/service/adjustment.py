"""Provides a service contract for AdjustmentDE-related services."""

__all__ = ["IAdjustmentService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import AdjustmentDE


class IAdjustmentService(
    ICrudService[AdjustmentDE],
    ABC,
):
    """A service contract for AdjustmentDE-related services."""
