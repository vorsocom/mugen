"""Provides an ORM for schema bindings."""

__all__ = ["SchemaBinding"]

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class SchemaBinding(ModelBase):
    """An ORM for ACP schema bindings to target resources/actions."""

    __tablename__ = "admin_schema_binding"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    schema_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_schema_definition.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    target_namespace: Mapped[str] = mapped_column(CITEXT(128), nullable=False)

    target_entity_set: Mapped[str] = mapped_column(CITEXT(128), nullable=False)

    target_action: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)

    binding_kind: Mapped[str] = mapped_column(CITEXT(64), nullable=False)

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(target_namespace)) > 0",
            name="ck_schema_binding__target_namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(target_entity_set)) > 0",
            name="ck_schema_binding__target_entity_set_nonempty",
        ),
        CheckConstraint(
            "length(btrim(binding_kind)) > 0",
            name="ck_schema_binding__binding_kind_nonempty",
        ),
        Index(
            "ux_schema_binding__tenant_target_kind_active",
            "tenant_id",
            "target_namespace",
            "target_entity_set",
            "target_action",
            "binding_kind",
            unique=True,
            postgresql_where=sa_text("is_active"),
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"SchemaBinding(id={self.id!r})"
