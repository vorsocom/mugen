"""Shared SQLAlchemy runtime resources for relational storage providers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


@dataclass(slots=True)
class SharedSQLAlchemyRuntime:
    """Owns one async engine/sessionmaker pair for relational providers."""

    engine: AsyncEngine
    session_maker: async_sessionmaker

    @staticmethod
    def _resolve_bool(value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _resolve_positive_int(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        if parsed <= 0:
            return default
        return parsed

    @staticmethod
    def _resolve_nonnegative_int(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        if parsed < 0:
            return default
        return parsed

    @staticmethod
    def _resolve_statement_timeout_ms(value: object) -> int | None:
        if value in [None, ""]:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
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
            getattr(sqlalchemy_cfg, "pool_recycle_seconds", 1800),
            default=1800,
        )
        pool_timeout = cls._resolve_positive_int(
            getattr(sqlalchemy_cfg, "pool_timeout_seconds", 30),
            default=30,
        )
        pool_size = cls._resolve_positive_int(
            getattr(sqlalchemy_cfg, "pool_size", 10),
            default=10,
        )
        max_overflow = cls._resolve_nonnegative_int(
            getattr(sqlalchemy_cfg, "max_overflow", 20),
            default=20,
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
