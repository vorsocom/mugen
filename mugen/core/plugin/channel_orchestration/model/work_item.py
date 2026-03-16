"""Provides an ORM for canonical channel intake work-item envelopes."""

from __future__ import annotations

__all__ = ["WorkItem"]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class WorkItem(ModelBase, TenantScopedMixin):
    """An ORM for canonicalized intake envelopes used by downstream execution."""

    __tablename__ = "channel_orchestration_work_item"

    trace_id: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    source: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    participants: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    content: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    attachments: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    signals: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    extractions: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    linked_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    linked_workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    replay_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    last_replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_chorch_work_item__trace_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(source)) > 0",
            name="ck_chorch_work_item__source_nonempty",
        ),
        CheckConstraint(
            "replay_count >= 0",
            name="ck_chorch_work_item__replay_count_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_work_item__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "trace_id",
            name="ux_chorch_work_item__tenant_trace_id",
        ),
        Index(
            "ix_chorch_work_item__tenant_source_created",
            "tenant_id",
            "source",
            "created_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkItem(id={self.id!r})"
