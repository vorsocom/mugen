"""Provides a service contract for SlaPolicyDE-related services."""

__all__ = ["ISlaPolicyService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaPolicyDE


class ISlaPolicyService(
    ICrudService[SlaPolicyDE],
    ABC,
):
    """A service contract for SlaPolicyDE-related services."""
