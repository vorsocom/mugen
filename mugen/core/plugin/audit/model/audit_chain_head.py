"""Provides an ORM for per-scope audit chain heads."""

__all__ = ["AuditChainHead"]

from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class AuditChainHead(ModelBase):
    """Tracks the latest sealed hash-chain state for an audit scope."""

    __tablename__ = "audit_chain_head"

    scope_key: Mapped[str] = mapped_column(CITEXT(256), nullable=False, index=True)
    last_seq: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )
    last_entry_hash: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        server_default=sa_text("''"),
    )

    __table_args__ = (
        UniqueConstraint("scope_key", name="ux_audit_chain_head__scope_key"),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return (
            f"AuditChainHead(scope_key={self.scope_key!r}, "
            f"last_seq={self.last_seq!r})"
        )
