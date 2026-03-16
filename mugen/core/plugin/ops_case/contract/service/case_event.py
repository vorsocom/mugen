"""Provides a service contract for CaseEventDE-related services."""

__all__ = ["ICaseEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_case.domain import CaseEventDE


class ICaseEventService(
    ICrudService[CaseEventDE],
    ABC,
):
    """A service contract for CaseEventDE-related services."""

