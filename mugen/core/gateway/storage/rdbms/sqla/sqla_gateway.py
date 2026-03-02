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
from mugen.core.utility.platforms import normalize_platforms


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
        """Validate relational connectivity and required schema compatibility."""
        async with self._engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
            for table_name, required in self._required_schema_checks().items():
                columns = await self._existing_columns(conn, table_name=table_name)
                missing_columns = sorted(required["columns"] - columns)
                if missing_columns:
                    missing_text = ", ".join(missing_columns)
                    raise RuntimeError(
                        "Database schema is not ready. "
                        "Run migrations before startup. "
                        f"mugen.{table_name} missing column(s): {missing_text}."
                    )

                constraints = await self._existing_constraints(
                    conn,
                    table_name=table_name,
                )
                missing_constraints = sorted(required["constraints"] - constraints)
                if missing_constraints:
                    missing_text = ", ".join(missing_constraints)
                    raise RuntimeError(
                        "Database schema is not ready. "
                        "Run migrations before startup. "
                        f"mugen.{table_name} missing constraint(s): {missing_text}."
                    )

                indexes = await self._existing_indexes(conn, table_name=table_name)
                missing_indexes = sorted(required["indexes"] - indexes)
                if missing_indexes:
                    missing_text = ", ".join(missing_indexes)
                    raise RuntimeError(
                        "Database schema is not ready. "
                        "Run migrations before startup. "
                        f"mugen.{table_name} missing index(es): {missing_text}."
                    )

    def _required_schema_checks(self) -> dict[str, dict[str, set[str]]]:
        checks: dict[str, dict[str, set[str]]] = {
            "core_keyval_entry": {
                "columns": {
                    "namespace",
                    "entry_key",
                    "payload",
                    "codec",
                    "row_version",
                    "expires_at",
                    "created_at",
                    "updated_at",
                },
                "constraints": {"pk_core_keyval_entry"},
                "indexes": {
                    "ix_core_keyval_entry_namespace_expires_at",
                    "ix_core_keyval_entry_namespace_entry_key_prefix",
                },
            },
        }
        platforms = normalize_platforms(
            getattr(getattr(self._config, "mugen", object()), "platforms", [])
        )
        if "web" not in platforms:
            return checks

        checks["web_queue_job"] = {
            "columns": {
                "job_id",
                "conversation_id",
                "sender",
                "message_type",
                "payload",
                "status",
                "attempts",
                "lease_expires_at",
                "error_message",
                "completed_at",
                "client_message_id",
                "created_at",
                "updated_at",
            },
            "constraints": {"ux_web_queue_job_job_id"},
            "indexes": {"ix_web_queue_job_status_lease"},
        }
        checks["web_conversation_state"] = {
            "columns": {
                "conversation_id",
                "owner_user_id",
                "stream_generation",
                "stream_version",
                "next_event_id",
            },
            "constraints": {"ux_web_conversation_state_conversation_id"},
            "indexes": {"ix_web_conversation_state_conversation_id"},
        }
        checks["web_conversation_event"] = {
            "columns": {
                "conversation_id",
                "event_id",
                "event_type",
                "payload",
                "stream_generation",
                "stream_version",
                "created_at",
            },
            "constraints": {"ux_web_conversation_event_conversation_id_event_id"},
            "indexes": {"ix_web_conversation_event_conversation_event_id"},
        }
        checks["web_media_token"] = {
            "columns": {
                "token",
                "owner_user_id",
                "conversation_id",
                "file_path",
                "expires_at",
            },
            "constraints": {"ux_web_media_token_token"},
            "indexes": {"ix_web_media_token_token"},
        }
        return checks

    async def _existing_columns(self, conn, *, table_name: str) -> set[str]:
        result = await conn.execute(
            sa_text(
                "SELECT column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = 'mugen' AND table_name = :table_name"
            ),
            {"table_name": table_name},
        )
        return {str(row.column_name) for row in result}

    async def _existing_constraints(self, conn, *, table_name: str) -> set[str]:
        result = await conn.execute(
            sa_text(
                "SELECT constraint_name "
                "FROM information_schema.table_constraints "
                "WHERE table_schema = 'mugen' "
                "AND table_name = :table_name "
                "AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')"
            ),
            {"table_name": table_name},
        )
        return {str(row.constraint_name) for row in result}

    async def _existing_indexes(self, conn, *, table_name: str) -> set[str]:
        result = await conn.execute(
            sa_text(
                "SELECT indexname "
                "FROM pg_indexes "
                "WHERE schemaname = 'mugen' AND tablename = :table_name"
            ),
            {"table_name": table_name},
        )
        return {str(row.indexname) for row in result}

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
