"""Provides a CRUD service for KPI thresholds."""

__all__ = ["KpiThresholdService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_reporting.contract.service.kpi_threshold import (
    IKpiThresholdService,
)
from mugen.core.plugin.ops_reporting.domain import KpiThresholdDE


class KpiThresholdService(  # pylint: disable=too-few-public-methods
    IRelationalService[KpiThresholdDE],
    IKpiThresholdService,
):
    """A CRUD service for KPI threshold boundaries."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KpiThresholdDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
