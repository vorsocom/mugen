"""Provides a service contract for SlaEscalationRunDE-related services."""

__all__ = ["ISlaEscalationRunService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaEscalationRunDE


class ISlaEscalationRunService(
    ICrudService[SlaEscalationRunDE],
    ABC,
):
    """A service contract for SlaEscalationRunDE-related services."""
