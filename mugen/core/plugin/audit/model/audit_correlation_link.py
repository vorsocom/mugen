"""Provides an ORM for audit correlation links."""

__all__ = ["AuditCorrelationLink"]

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class AuditCorrelationLink(ModelBase):
    """Correlation link emitted for ACP request/audit operations."""

    __tablename__ = "audit_correlation_link"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    trace_id: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    correlation_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )

    source_plugin: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    entity_set: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    operation: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)

    action_name: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )

    parent_entity_set: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)

    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "ix_audit_correlation_link__trace_occurred",
            "trace_id",
            "occurred_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"AuditCorrelationLink(id={self.id!r})"
