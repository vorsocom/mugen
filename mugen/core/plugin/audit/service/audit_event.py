"""Provides a CRUD service for audit events."""

__all__ = ["AuditEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.audit.contract.service.audit_event import IAuditEventService
from mugen.core.plugin.audit.domain import AuditEventDE


class AuditEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[AuditEventDE],
    IAuditEventService,
):
    """A CRUD service for audit events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AuditEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
