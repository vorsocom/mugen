"""Provides an ORM for channel orchestration ingress bindings."""

__all__ = ["IngressBinding"]

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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class IngressBinding(ModelBase, TenantScopedMixin):
    """An ORM for tenant-scoped ingress identifier bindings."""

    __tablename__ = "channel_orchestration_ingress_binding"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    channel_key: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    identifier_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    identifier_value: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
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
            name="ck_chorch_ingress_binding__channel_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(identifier_type)) > 0",
            name="ck_chorch_ingress_binding__identifier_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(identifier_value)) > 0",
            name="ck_chorch_ingress_binding__identifier_value_nonempty",
        ),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_chorch_ingress_binding__service_route_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_ingress_binding__tenant_id_id",
        ),
        Index(
            "ix_chorch_ingress_binding__tenant_channel_identifier_active",
            "tenant_id",
            "channel_key",
            "identifier_type",
            "identifier_value",
            "is_active",
        ),
        Index(
            "ix_chorch_ingress_binding__channel_identifier_active",
            "channel_key",
            "identifier_type",
            "identifier_value",
            "is_active",
        ),
        Index(
            "ux_chorch_ingress_binding__tci_active_unique",
            "tenant_id",
            "channel_key",
            "identifier_type",
            "identifier_value",
            unique=True,
            postgresql_where=sa_text("is_active = true"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"IngressBinding(id={self.id!r})"
