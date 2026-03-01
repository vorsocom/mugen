"""Provides an SQLAlchemy-backed implementation of IRelationalStorageGateway."""

__all__ = ["SQLAlchemyRelationalStorageGateway"]

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from sqlalchemy import Table
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
)

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork
from mugen.core.gateway.storage.rdbms.sqla import build_table_registry_from_base
from mugen.core.gateway.storage.rdbms.sqla.sqla_uow import (
    SQLAlchemyRelationalUnitOfWork,
    TableRegistry,
)
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime


class SQLAlchemyRelationalStorageGateway(IRelationalStorageGateway):
    """An SQLAlchemy-backed implementation of IRelationalStorageGateway.

    This gateway wires SQLAlchemy's async engine and session machinery into the
    relational gateway contracts used by muGen. It is responsible for:

        - Creating `AsyncSession` instances.
        - Starting and managing transactions.
        - Constructing `SQLAlchemyRelationalUnitOfWork` instances bound to each
        transaction.
    """

    def __init__(
        self,
        config,
        logging_gateway: ILoggingGateway,
        relational_runtime: SharedSQLAlchemyRuntime,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._runtime = relational_runtime
        self._engine: AsyncEngine = self._runtime.engine
        self._tables: TableRegistry = build_table_registry_from_base(ModelBase)
        self._session_maker: async_sessionmaker = self._runtime.session_maker

    async def aclose(self) -> None:
        """Shared engine lifecycle is managed by DI runtime shutdown."""
        return None

    async def check_readiness(self) -> None:
        """Validate relational connectivity for fail-fast startup checks."""
        async with self._engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[IRelationalUnitOfWork]:
        """Yield a SQLAlchemyRelationalUnitOfWork bound to a transaction.

        This method fulfills the `IRelationalStorageGateway.unit_of_work` contract by:
            - Creating an `AsyncSession` from the configured session maker.
            - Starting a transaction (`session.begin()`).
            - Yielding a `SQLAlchemyRelationalUnitOfWork` bound to that session.
            - Committing the transaction on normal exit.
            - Rolling back the transaction if an exception is raised.
        """
        async with self._session_maker() as session:
            async with session.begin():
                uow = SQLAlchemyRelationalUnitOfWork(session, self._tables)
                yield uow
                # commit / rollback handled by session.begin()

    def register_tables(
        self,
        mapping: Mapping[str, Table],
    ) -> None:
        """Register multiple tables under their logical names.

        This method lets core code and extensions add one or more tables to the
        gateway's internal registry after the gateway has been created.

        Parameters
        ----------
        mapping:
            Mapping of logical name -> SQLAlchemy `Table`.

        Raises
        ------
        ValueError
            If any logical name in `mapping` is already registered.
        """
        collisions = [name for name in mapping if name in self._tables]
        if collisions:
            joined = ", ".join(repr(n) for n in collisions)
            raise ValueError(f"Tables already registered for: {joined}")

        self._tables.update(mapping)
