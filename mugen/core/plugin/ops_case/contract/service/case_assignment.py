"""Provides a service contract for CaseAssignmentDE-related services."""

__all__ = ["ICaseAssignmentService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_case.domain import CaseAssignmentDE


class ICaseAssignmentService(
    ICrudService[CaseAssignmentDE],
    ABC,
):
    """A service contract for CaseAssignmentDE-related services."""

