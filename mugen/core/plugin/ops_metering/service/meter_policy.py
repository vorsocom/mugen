"""Provides a CRUD service for meter policies."""

__all__ = ["MeterPolicyService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_metering.contract.service.meter_policy import (
    IMeterPolicyService,
)
from mugen.core.plugin.ops_metering.domain import MeterPolicyDE


class MeterPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[MeterPolicyDE],
    IMeterPolicyService,
):
    """A CRUD service for metering policy definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=MeterPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
