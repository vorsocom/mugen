"""Shared SQLAlchemy runtime resources for relational storage providers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from mugen.core.utility.config_value import parse_bool_flag


@dataclass(slots=True)
class SharedSQLAlchemyRuntime:
    """Owns one async engine/sessionmaker pair for relational providers."""

    engine: AsyncEngine
    session_maker: async_sessionmaker

    @staticmethod
    def _resolve_bool(value: object, default: bool) -> bool:
        return parse_bool_flag(value, default)

    @staticmethod
    def _resolve_positive_int(
        value: object,
        *,
        default: int,
        field_name: str,
    ) -> int:
        if value in [None, ""]:
            return default
        if isinstance(value, bool):
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a positive integer."
            )
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a positive integer."
            ) from exc
        if parsed <= 0:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be greater than 0."
            )
        return parsed

    @staticmethod
    def _resolve_nonnegative_int(
        value: object,
        *,
        default: int,
        field_name: str,
    ) -> int:
        if value in [None, ""]:
            return default
        if isinstance(value, bool):
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a non-negative integer."
            )
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a non-negative integer."
            ) from exc
        if parsed < 0:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be greater than or equal to 0."
            )
        return parsed

    @staticmethod
    def _resolve_statement_timeout_ms(value: object) -> int | None:
        if value in [None, ""]:
            return None
        if isinstance(value, bool):
            raise RuntimeError(
                "Invalid configuration: rdbms.sqlalchemy.statement_timeout_ms must be "
                "a positive integer."
            )
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Invalid configuration: rdbms.sqlalchemy.statement_timeout_ms must be "
                "a positive integer."
            ) from exc
        if parsed <= 0:
            raise RuntimeError(
                "Invalid configuration: rdbms.sqlalchemy.statement_timeout_ms must be "
                "greater than 0."
            )
        return parsed

    @classmethod
    def from_config(cls, config: SimpleNamespace) -> "SharedSQLAlchemyRuntime":
        sqlalchemy_cfg = getattr(
            getattr(config, "rdbms", SimpleNamespace()),
            "sqlalchemy",
            None,
        )
        sqlalchemy_url = getattr(
            sqlalchemy_cfg,
            "url",
            None,
        )
        if not isinstance(sqlalchemy_url, str) or sqlalchemy_url.strip() == "":
            raise RuntimeError("Relational storage requires rdbms.sqlalchemy.url.")
        url = sqlalchemy_url.strip()
        pool_pre_ping = cls._resolve_bool(
            getattr(sqlalchemy_cfg, "pool_pre_ping", True),
            default=True,
        )
        pool_recycle = cls._resolve_positive_int(
            getattr(sqlalchemy_cfg, "pool_recycle_seconds", None),
            default=1800,
            field_name="rdbms.sqlalchemy.pool_recycle_seconds",
        )
        pool_timeout = cls._resolve_positive_int(
            getattr(sqlalchemy_cfg, "pool_timeout_seconds", None),
            default=30,
            field_name="rdbms.sqlalchemy.pool_timeout_seconds",
        )
        pool_size = cls._resolve_positive_int(
            getattr(sqlalchemy_cfg, "pool_size", None),
            default=10,
            field_name="rdbms.sqlalchemy.pool_size",
        )
        max_overflow = cls._resolve_nonnegative_int(
            getattr(sqlalchemy_cfg, "max_overflow", None),
            default=20,
            field_name="rdbms.sqlalchemy.max_overflow",
        )
        statement_timeout_ms = cls._resolve_statement_timeout_ms(
            getattr(sqlalchemy_cfg, "statement_timeout_ms", None),
        )

        connect_args: dict[str, object] = {}
        if statement_timeout_ms is not None:
            drivername = make_url(url).drivername
            if drivername.endswith("+asyncpg"):
                connect_args["server_settings"] = {
                    "statement_timeout": str(statement_timeout_ms),
                }
            elif drivername.endswith("+psycopg"):
                connect_args["options"] = f"-c statement_timeout={statement_timeout_ms}"

        engine_kwargs: dict[str, object] = {
            "pool_pre_ping": pool_pre_ping,
            "pool_recycle": pool_recycle,
            "pool_timeout": pool_timeout,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
        }
        if connect_args:
            engine_kwargs["connect_args"] = connect_args

        engine = create_async_engine(
            url,
            **engine_kwargs,
        )
        session_maker = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        return cls(engine=engine, session_maker=session_maker)

    async def aclose(self) -> None:
        """Dispose engine resources exactly once."""
        await self.engine.dispose()
