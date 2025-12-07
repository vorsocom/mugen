"""Provides an abstract base class for creating relational database storage gateways."""

__all__ = ["IRelationalStorageGateway"]

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork


# pylint: disable=too-few-public-methods
class IRelationalStorageGateway(ABC):
    """An abstract base class for creating relational database storage gateways.

    Provides transactional access via IRelationalUnitOfWork.
    """

    @asynccontextmanager
    @abstractmethod
    async def unit_of_work(self) -> AsyncIterator[IRelationalUnitOfWork]:
        """Yield a transactional unit of work.

        Implementation should:
            - open a connection/session.
            - start a transaction.
            - commit on a normal exit.
            - rollback on exception.

        Example
        -------
        uow: IRelationalUnitOfWork
        async with gateway.unit_of_work() as uow:
            await uow.insert("users", {"id": 1, "name": "Alice"})
            await uow.insert("profiles", {"user_id": 1, "bio": "..."})
        """
