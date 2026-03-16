"""Provides an ORM for orchestration decision timeline events."""

__all__ = ["OrchestrationEvent"]

from datetime import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class OrchestrationEvent(ModelBase, TenantScopedMixin):
    """An ORM for append-only orchestration events."""

    __tablename__ = "channel_orchestration_orchestration_event"

    conversation_state_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_conversation_state.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    sender_key: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    decision: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    source: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IS NOT NULL AND length(btrim(event_type)) > 0",
            name="ck_chorch_event__type_nonempty",
        ),
        CheckConstraint(
            "decision IS NULL OR length(btrim(decision)) > 0",
            name="ck_chorch_event__decision_nonempty_if_set",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_chorch_event__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "source IS NULL OR length(btrim(source)) > 0",
            name="ck_chorch_event__source_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_event__tenant_id_id",
        ),
        Index(
            "ix_chorch_event__tenant_conversation_occurred",
            "tenant_id",
            "conversation_state_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"OrchestrationEvent(id={self.id!r})"
