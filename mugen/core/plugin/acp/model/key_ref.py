"""Provides an ORM for key reference registry entries."""

__all__ = ["KeyRef"]

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class KeyRefStatus(str, enum.Enum):
    """Lifecycle values for managed key references."""

    ACTIVE = "active"
    RETIRED = "retired"
    DESTROYED = "destroyed"


# pylint: disable=too-few-public-methods
class KeyRef(ModelBase):
    """Metadata registry for tenant/global scoped key references."""

    __tablename__ = "admin_key_ref"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    purpose: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    key_id: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'local'"),
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            KeyRefStatus,
            name="admin_key_ref_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    retired_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    retired_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    destroyed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    destroyed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    destroy_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    encrypted_secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    has_material: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    material_last_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    material_last_set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(purpose)) > 0",
            name="ck_key_ref__purpose_nonempty",
        ),
        CheckConstraint(
            "length(btrim(key_id)) > 0",
            name="ck_key_ref__key_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(provider)) > 0",
            name="ck_key_ref__provider_nonempty",
        ),
        CheckConstraint(
            "retired_reason IS NULL OR length(btrim(retired_reason)) > 0",
            name="ck_key_ref__retired_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "destroy_reason IS NULL OR length(btrim(destroy_reason)) > 0",
            name="ck_key_ref__destroy_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_key_ref__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "purpose",
            "key_id",
            name="ux_key_ref__tenant_purpose_key",
        ),
        Index(
            "ux_key_ref__tenant_purpose_active",
            "tenant_id",
            "purpose",
            unique=True,
            postgresql_where=sa_text("status = 'active'"),
        ),
        Index(
            "ix_key_ref__tenant_purpose_status",
            "tenant_id",
            "purpose",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KeyRef(id={self.id!r})"
