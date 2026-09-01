"""Provides the Service Profile ingress assignment ORM."""

from __future__ import annotations

__all__ = ["ServiceProfileIngressBinding"]

import uuid

from sqlalchemy import Boolean, ForeignKeyConstraint, Index, UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class ServiceProfileIngressBinding(ModelBase, TenantScopedMixin):
    """An exact tenant-scoped association to a Core Ingress Binding."""

    __tablename__ = "service_profile_ingress_binding"

    service_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    ingress_binding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        server_default=sa_text("true"),
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "service_profile_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.service_profile_service_profile.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.service_profile_service_profile.id",
            ),
            name="fkx_service_profile_ingress__tenant_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "ingress_binding_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.channel_orchestration_ingress_binding.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.channel_orchestration_ingress_binding.id",
            ),
            name="fkx_service_profile_ingress__tenant_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_service_profile_ingress__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "service_profile_id",
            "ingress_binding_id",
            name="ux_service_profile_ingress__tenant_profile_binding",
        ),
        Index(
            "ux_service_profile_ingress__active_binding",
            "tenant_id",
            "ingress_binding_id",
            unique=True,
            postgresql_where=sa_text("is_active = true"),
        ),
        Index(
            "ix_service_profile_ingress__tenant_profile_active",
            "tenant_id",
            "service_profile_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ServiceProfileIngressBinding(id={self.id!r})"
