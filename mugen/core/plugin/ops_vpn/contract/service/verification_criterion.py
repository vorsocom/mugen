"""Provides a service contract for VerificationCriterionDE-related services."""

__all__ = ["IVerificationCriterionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VerificationCriterionDE


class IVerificationCriterionService(
    ICrudService[VerificationCriterionDE],
    ABC,
):
    """A service contract for VerificationCriterionDE-related services."""
