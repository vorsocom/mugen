"""Shared SQLAlchemy runtime resources for relational storage providers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


@dataclass(slots=True)
class SharedSQLAlchemyRuntime:
    """Owns one async engine/sessionmaker pair for relational providers."""

    engine: AsyncEngine
    session_maker: async_sessionmaker

    @classmethod
    def from_config(cls, config: SimpleNamespace) -> "SharedSQLAlchemyRuntime":
        sqlalchemy_url = getattr(
            getattr(getattr(config, "rdbms", SimpleNamespace()), "sqlalchemy", None),
            "url",
            None,
        )
        if not isinstance(sqlalchemy_url, str) or sqlalchemy_url.strip() == "":
            raise RuntimeError("Relational storage requires rdbms.sqlalchemy.url.")
        engine = create_async_engine(sqlalchemy_url.strip())
        session_maker = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        return cls(engine=engine, session_maker=session_maker)

    async def aclose(self) -> None:
        """Dispose engine resources exactly once."""
        await self.engine.dispose()
