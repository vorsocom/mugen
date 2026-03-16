"""Provides an ORM for plugin capability grant records."""

__all__ = ["PluginCapabilityGrant"]

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class PluginCapabilityGrant(ModelBase):
    """Tenant/global grants for runtime plugin capabilities."""

    __tablename__ = "admin_plugin_capability_grant"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    plugin_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'[]'::jsonb"),
    )

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    revoke_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(plugin_key)) > 0",
            name="ck_plugin_capability_grant__plugin_key_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(capabilities) = 'array'",
            name="ck_plugin_capability_grant__capabilities_is_array",
        ),
        CheckConstraint(
            "jsonb_array_length(capabilities) > 0",
            name="ck_plugin_capability_grant__capabilities_nonempty",
        ),
        CheckConstraint(
            "revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0",
            name="ck_plugin_capability_grant__revoke_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_plugin_capability_grant__tenant_id_id",
        ),
        Index(
            "ux_plugin_capability_grant__tenant_plugin_active",
            "tenant_id",
            "plugin_key",
            unique=True,
            postgresql_where=sa_text("revoked_at IS NULL"),
        ),
        Index(
            "ix_plugin_capability_grant__tenant_plugin",
            "tenant_id",
            "plugin_key",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"PluginCapabilityGrant(id={self.id!r})"
