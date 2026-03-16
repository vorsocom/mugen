"""Provides a CRUD service for case assignment history."""

__all__ = ["CaseAssignmentService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_case.contract.service.case_assignment import (
    ICaseAssignmentService,
)
from mugen.core.plugin.ops_case.domain import CaseAssignmentDE


class CaseAssignmentService(  # pylint: disable=too-few-public-methods
    IRelationalService[CaseAssignmentDE],
    ICaseAssignmentService,
):
    """A CRUD service for case assignment history."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CaseAssignmentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

