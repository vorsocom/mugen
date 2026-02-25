"""Provides an ORM for schema definitions."""

__all__ = ["SchemaDefinition"]

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer
from sqlalchemy import UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class SchemaDefinitionStatus(str, enum.Enum):
    """Schema definition lifecycle statuses."""

    DRAFT = "draft"

    ACTIVE = "active"

    INACTIVE = "inactive"


# pylint: disable=too-few-public-methods
class SchemaDefinition(ModelBase):
    """An ORM for ACP schema definitions."""

    __tablename__ = "admin_schema_definition"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    key: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)

    description: Mapped[str | None] = mapped_column(CITEXT(2048), nullable=True)

    schema_kind: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'json_schema'"),
    )

    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        PGENUM(
            SchemaDefinitionStatus,
            name="admin_schema_definition_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("'draft'"),
        index=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    checksum_sha256: Mapped[str] = mapped_column(CITEXT(64), nullable=False)

    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_schema_definition__key_nonempty",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_schema_definition__version_positive",
        ),
        UniqueConstraint(
            "tenant_id",
            "key",
            "version",
            name="ux_schema_definition__tenant_key_version",
        ),
        Index(
            "ux_schema_definition__tenant_key_active",
            "tenant_id",
            "key",
            unique=True,
            postgresql_where=sa_text("status = 'active'"),
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"SchemaDefinition(id={self.id!r})"
