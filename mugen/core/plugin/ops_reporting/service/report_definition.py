"""Provides a CRUD service for report definitions."""

__all__ = ["ReportDefinitionService"]

from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_reporting.contract.service.report_definition import (
    IReportDefinitionService,
)
from mugen.core.plugin.ops_reporting.domain import ReportDefinitionDE


class ReportDefinitionService(  # pylint: disable=too-few-public-methods
    IRelationalService[ReportDefinitionDE],
    IReportDefinitionService,
):
    """A CRUD service for report definition metadata."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ReportDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> ReportDefinitionDE:
        create_values = dict(values)
        metric_codes = create_values.get("metric_codes")
        if metric_codes is not None:
            create_values["metric_codes"] = [
                str(code).strip()
                for code in metric_codes
                if str(code or "").strip()
            ]

        return await super().create(create_values)
