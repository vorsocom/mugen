"""Provides an ORM for legal hold records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Uuid
from sqlalchemy import UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class LegalHold(ModelBase, TenantScopedMixin):
    """Legal hold records synchronized to governed resources."""

    __tablename__ = "ops_governance_legal_hold"

    retention_class_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    resource_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    reason: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'active'"),
        index=True,
    )

    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    placed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    released_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    release_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "retention_class_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_governance_retention_class.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_governance_retention_class.id",
            ),
            name="fkx_ops_gov_legal_hold__tenant_retention_class",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_legal_hold__resource_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_ops_gov_legal_hold__reason_nonempty",
        ),
        CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_ops_gov_legal_hold__status_valid",
        ),
        CheckConstraint(
            "release_reason IS NULL OR length(btrim(release_reason)) > 0",
            name="ck_ops_gov_legal_hold__release_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_legal_hold__tenant_id_id",
        ),
        Index(
            "ix_ops_gov_legal_hold__tenant_resource_status",
            "tenant_id",
            "resource_type",
            "resource_id",
            "status",
        ),
        Index(
            "ux_ops_gov_legal_hold__tenant_resource_active",
            "tenant_id",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=sa_text("status = 'active'"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"LegalHold(id={self.id!r})"
