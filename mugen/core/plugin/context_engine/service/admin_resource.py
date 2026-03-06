"""ACP CRUD services for context_engine-managed resources."""

from __future__ import annotations

__all__ = [
    "ContextContributorBindingService",
    "ContextPolicyService",
    "ContextProfileService",
    "ContextSourceBindingService",
    "ContextTracePolicyService",
]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.context_engine.domain import (
    ContextContributorBindingDE,
    ContextPolicyDE,
    ContextProfileDE,
    ContextSourceBindingDE,
    ContextTracePolicyDE,
)


class ContextProfileService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextProfileDE]
):
    """CRUD service for ContextProfile rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=ContextProfileDE, table=table, rsg=rsg, **kwargs)


class ContextPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextPolicyDE]
):
    """CRUD service for ContextPolicy rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=ContextPolicyDE, table=table, rsg=rsg, **kwargs)


class ContextContributorBindingService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextContributorBindingDE]
):
    """CRUD service for ContextContributorBinding rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextContributorBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


class ContextSourceBindingService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextSourceBindingDE]
):
    """CRUD service for ContextSourceBinding rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextSourceBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


class ContextTracePolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextTracePolicyDE]
):
    """CRUD service for ContextTracePolicy rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextTracePolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
