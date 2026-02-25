"""Provides a CRUD service for SLA escalation-run audit records."""

__all__ = ["SlaEscalationRunService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_escalation_run import (
    ISlaEscalationRunService,
)
from mugen.core.plugin.ops_sla.domain import SlaEscalationRunDE


class SlaEscalationRunService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaEscalationRunDE],
    ISlaEscalationRunService,
):
    """A CRUD service for escalation run persistence."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaEscalationRunDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
