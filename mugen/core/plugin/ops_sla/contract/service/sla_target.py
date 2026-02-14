"""Provides a service contract for SlaTargetDE-related services."""

__all__ = ["ISlaTargetService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaTargetDE


class ISlaTargetService(
    ICrudService[SlaTargetDE],
    ABC,
):
    """A service contract for SlaTargetDE-related services."""
