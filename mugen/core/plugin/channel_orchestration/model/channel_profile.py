"""Provides an ORM for channel orchestration channel profiles."""

__all__ = ["ChannelProfile"]

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
class ChannelProfile(ModelBase, TenantScopedMixin):
    """An ORM for channel profiles used by orchestration policies and rules."""

    __tablename__ = "channel_orchestration_channel_profile"

    channel_key: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    profile_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    route_default_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.channel_orchestration_orchestration_policy.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(channel_key)) > 0",
            name="ck_chorch_profile__channel_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_chorch_profile__profile_key_nonempty",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_chorch_profile__display_name_nonempty_if_set",
        ),
        CheckConstraint(
            "route_default_key IS NULL OR length(btrim(route_default_key)) > 0",
            name="ck_chorch_profile__route_default_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_profile__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "channel_key",
            "profile_key",
            name="ux_chorch_profile__tenant_channel_profile",
        ),
        Index(
            "ix_chorch_profile__tenant_channel_active",
            "tenant_id",
            "channel_key",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ChannelProfile(id={self.id!r})"
