"""Provides an ORM for SLA policies."""

__all__ = ["SlaPolicy"]

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class SlaPolicy(ModelBase, TenantScopedMixin):
    """An ORM for SLA policy definitions."""

    __tablename__ = "ops_sla_policy"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "mugen.ops_sla_calendar.id",
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
            "length(btrim(code)) > 0",
            name="ck_ops_sla_policy__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_policy__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_sla_policy__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_sla_policy__tenant_code",
        ),
        Index(
            "ix_ops_sla_policy__tenant_calendar",
            "tenant_id",
            "calendar_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"SlaPolicy(id={self.id!r})"
