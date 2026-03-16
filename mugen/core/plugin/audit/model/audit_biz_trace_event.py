"""Provides an ORM for audit business trace events."""

__all__ = ["AuditBizTraceEvent"]

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class AuditBizTraceEvent(ModelBase):
    """Observability timeline event emitted for ACP request lifecycle."""

    __tablename__ = "audit_biz_trace_event"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    trace_id: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    span_id: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)

    parent_span_id: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True)

    correlation_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )

    source_plugin: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    entity_set: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )

    action_name: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )

    stage: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)

    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_audit_biz_trace_event__trace_occurred",
            "trace_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"AuditBizTraceEvent(id={self.id!r})"
