"""Provides an ORM for channel orchestration sender blocklist entries."""

__all__ = ["BlocklistEntry"]

from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
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


# pylint: disable=too-few-public-methods
class BlocklistEntry(ModelBase, TenantScopedMixin):
    """An ORM for tenant/channel sender blocklist entries."""

    __tablename__ = "channel_orchestration_blocklist_entry"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    sender_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    blocked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    unblocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    unblocked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    unblock_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(sender_key)) > 0",
            name="ck_chorch_blocklist__sender_nonempty",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_chorch_blocklist__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "unblock_reason IS NULL OR length(btrim(unblock_reason)) > 0",
            name="ck_chorch_blocklist__unblock_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_blocklist__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "channel_profile_id",
            "sender_key",
            "is_active",
            name="ux_chorch_blocklist__tenant_profile_sender_active",
        ),
        Index(
            "ix_chorch_blocklist__tenant_sender_active_expiry",
            "tenant_id",
            "sender_key",
            "is_active",
            "expires_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"BlocklistEntry(id={self.id!r})"
