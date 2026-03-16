"""Provides a service contract for MeterPolicyDE-related services."""

__all__ = ["IMeterPolicyService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_metering.domain import MeterPolicyDE


class IMeterPolicyService(
    ICrudService[MeterPolicyDE],
    ABC,
):
    """A service contract for MeterPolicyDE-related services."""
