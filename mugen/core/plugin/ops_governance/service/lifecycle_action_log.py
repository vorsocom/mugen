"""Provides a CRUD service for lifecycle action logs."""

__all__ = ["LifecycleActionLogService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.contract.service.lifecycle_action_log import (
    ILifecycleActionLogService,
)
from mugen.core.plugin.ops_governance.domain import LifecycleActionLogDE


class LifecycleActionLogService(  # pylint: disable=too-few-public-methods
    IRelationalService[LifecycleActionLogDE],
    ILifecycleActionLogService,
):
    """A CRUD service for append-only lifecycle action log entries."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=LifecycleActionLogDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
