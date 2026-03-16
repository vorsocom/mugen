"""Provides an ORM for channel orchestration intake rules."""

__all__ = ["IntakeRule"]

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


# pylint: disable=too-few-public-methods
class IntakeRule(ModelBase, TenantScopedMixin):
    """An ORM for intake matching rules."""

    __tablename__ = "channel_orchestration_intake_rule"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    match_kind: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    match_value: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
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
            "length(btrim(name)) > 0",
            name="ck_chorch_intake_rule__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(match_kind)) > 0",
            name="ck_chorch_intake_rule__kind_nonempty",
        ),
        CheckConstraint(
            "length(btrim(match_value)) > 0",
            name="ck_chorch_intake_rule__value_nonempty",
        ),
        CheckConstraint(
            "route_key IS NULL OR length(btrim(route_key)) > 0",
            name="ck_chorch_intake_rule__route_nonempty_if_set",
        ),
        CheckConstraint(
            "priority >= 0",
            name="ck_chorch_intake_rule__priority_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_intake_rule__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "channel_profile_id",
            "name",
            name="ux_chorch_intake_rule__tenant_profile_name",
        ),
        Index(
            "ix_chorch_intake_rule__tenant_profile_kind_priority",
            "tenant_id",
            "channel_profile_id",
            "match_kind",
            "priority",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"IntakeRule(id={self.id!r})"
