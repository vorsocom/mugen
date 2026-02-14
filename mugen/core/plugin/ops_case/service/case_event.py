"""Provides a CRUD service for case timeline events."""

__all__ = ["CaseEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_case.contract.service.case_event import ICaseEventService
from mugen.core.plugin.ops_case.domain import CaseEventDE


class CaseEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[CaseEventDE],
    ICaseEventService,
):
    """A CRUD service for case timeline events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CaseEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

