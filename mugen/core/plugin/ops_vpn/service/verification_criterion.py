"""Provides a CRUD service for verification criteria."""

__all__ = ["VerificationCriterionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_vpn.contract.service.verification_criterion import (
    IVerificationCriterionService,
)
from mugen.core.plugin.ops_vpn.domain import VerificationCriterionDE


class VerificationCriterionService(  # pylint: disable=too-few-public-methods
    IRelationalService[VerificationCriterionDE],
    IVerificationCriterionService,
):
    """A CRUD service for verification criteria."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VerificationCriterionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
