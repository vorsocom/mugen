"""Provides a service contract for AggregationJobDE-related services."""

__all__ = ["IAggregationJobService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_reporting.domain import AggregationJobDE


class IAggregationJobService(
    ICrudService[AggregationJobDE],
    ABC,
):
    """A service contract for AggregationJobDE-related services."""
