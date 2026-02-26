"""Provides a service contract for LifecycleActionLog services."""

__all__ = ["ILifecycleActionLogService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_governance.domain import LifecycleActionLogDE


class ILifecycleActionLogService(ICrudService[LifecycleActionLogDE], ABC):
    """A service contract for append-only lifecycle action logs."""
