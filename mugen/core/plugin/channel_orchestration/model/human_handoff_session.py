"""Provides an ORM for durable human handoff sessions."""

__all__ = ["HumanHandoffSession"]

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
class HumanHandoffSession(ModelBase, TenantScopedMixin):
    """An ORM for conversation-scoped human handoff state."""

    __tablename__ = "channel_orchestration_human_handoff_session"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)
    channel_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    room_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    sender_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )
    client_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.admin_messaging_client_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'active'"),
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    deactivated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deactivation_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_human_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_delivery_status: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )
    last_delivery_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_chorch_handoff__scope_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_chorch_handoff__platform_nonempty",
        ),
        CheckConstraint(
            "channel_id IS NULL OR length(btrim(channel_id)) > 0",
            name="ck_chorch_handoff__channel_nonempty_if_set",
        ),
        CheckConstraint(
            "room_id IS NULL OR length(btrim(room_id)) > 0",
            name="ck_chorch_handoff__room_nonempty_if_set",
        ),
        CheckConstraint(
            "sender_id IS NULL OR length(btrim(sender_id)) > 0",
            name="ck_chorch_handoff__sender_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "conversation_id IS NULL OR "
                "length(btrim(conversation_id)) > 0"
            ),
            name="ck_chorch_handoff__conversation_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_chorch_handoff__service_route_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_chorch_handoff__status_nonempty",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_chorch_handoff__reason_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "deactivation_reason IS NULL OR "
                "length(btrim(deactivation_reason)) > 0"
            ),
            name="ck_chorch_handoff__deactivation_reason_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "last_delivery_status IS NULL OR "
                "length(btrim(last_delivery_status)) > 0"
            ),
            name="ck_chorch_handoff__delivery_status_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "last_delivery_error IS NULL OR "
                "length(btrim(last_delivery_error)) > 0"
            ),
            name="ck_chorch_handoff__delivery_error_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_handoff__tenant_id_id",
        ),
        Index(
            "ux_chorch_handoff__tenant_scope_active",
            "tenant_id",
            "scope_key",
            unique=True,
            postgresql_where=sa_text("status = 'active'"),
        ),
        Index(
            "ix_chorch_handoff__tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"HumanHandoffSession(id={self.id!r})"
