"""Provides an ORM for channel orchestration routing rules."""

__all__ = ["RoutingRule"]

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
class RoutingRule(ModelBase, TenantScopedMixin):
    """An ORM for route ownership and destination metadata."""

    __tablename__ = "channel_orchestration_routing_rule"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    route_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    target_queue_name: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    target_service_key: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    target_namespace: Mapped[str | None] = mapped_column(
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
            "length(btrim(route_key)) > 0",
            name="ck_chorch_routing_rule__route_nonempty",
        ),
        CheckConstraint(
            "target_queue_name IS NULL OR length(btrim(target_queue_name)) > 0",
            name="ck_chorch_routing_rule__queue_nonempty_if_set",
        ),
        CheckConstraint(
            "target_service_key IS NULL OR length(btrim(target_service_key)) > 0",
            name="ck_chorch_routing_rule__svc_key_nonempty_if_set",
        ),
        CheckConstraint(
            "target_namespace IS NULL OR length(btrim(target_namespace)) > 0",
            name="ck_chorch_routing_rule__namespace_nonempty_if_set",
        ),
        CheckConstraint(
            "priority >= 0",
            name="ck_chorch_routing_rule__priority_nonnegative",
        ),
        CheckConstraint(
            (
                "target_queue_name IS NOT NULL OR owner_user_id IS NOT NULL OR "
                "target_service_key IS NOT NULL"
            ),
            name="ck_chorch_routing_rule__target_required",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_routing_rule__tenant_id_id",
        ),
        Index(
            "ix_chorch_routing_rule__tenant_profile_route_active",
            "tenant_id",
            "channel_profile_id",
            "route_key",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"RoutingRule(id={self.id!r})"
