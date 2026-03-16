"""Provides an ORM for channel orchestration throttle rules."""

__all__ = ["ThrottleRule"]

import uuid

from sqlalchemy import (
    BigInteger,
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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class ThrottleRule(ModelBase, TenantScopedMixin):
    """An ORM for throttle policies evaluated at intake time."""

    __tablename__ = "channel_orchestration_throttle_rule"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    sender_scope: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'sender'"),
        index=True,
    )

    window_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("60"),
    )

    max_messages: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("20"),
    )

    block_on_violation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
    )

    block_duration_seconds: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    priority: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("100"),
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
            "length(btrim(code)) > 0",
            name="ck_chorch_throttle__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(sender_scope)) > 0",
            name="ck_chorch_throttle__scope_nonempty",
        ),
        CheckConstraint(
            "window_seconds > 0",
            name="ck_chorch_throttle__window_positive",
        ),
        CheckConstraint(
            "max_messages > 0",
            name="ck_chorch_throttle__max_positive",
        ),
        CheckConstraint(
            "block_duration_seconds IS NULL OR block_duration_seconds >= 0",
            name="ck_chorch_throttle__duration_nonnegative",
        ),
        CheckConstraint(
            "priority >= 0",
            name="ck_chorch_throttle__priority_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_throttle__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_chorch_throttle__tenant_code",
        ),
        Index(
            "ix_chorch_throttle__tenant_profile_active_priority",
            "tenant_id",
            "channel_profile_id",
            "is_active",
            "priority",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ThrottleRule(id={self.id!r})"
