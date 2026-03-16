"""Provides a service contract for MetricSeriesDE-related services."""

__all__ = ["IMetricSeriesService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_reporting.domain import MetricSeriesDE


class IMetricSeriesService(
    ICrudService[MetricSeriesDE],
    ABC,
):
    """A service contract for MetricSeriesDE-related services."""
