"""Provides an ORM for retention class definitions."""

from __future__ import annotations

__all__ = ["RetentionClass"]

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
class RetentionClass(ModelBase, TenantScopedMixin):
    """Retention profile used by lifecycle orchestration."""

    __tablename__ = "ops_governance_retention_class"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    resource_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    retention_days: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    redaction_after_days: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    purge_grace_days: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("30"),
    )

    legal_hold_allowed: Mapped[bool] = mapped_column(
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

    description: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_retention_class__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_retention_class__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_retention_class__resource_type_nonempty",
        ),
        CheckConstraint(
            "retention_days >= 0",
            name="ck_ops_gov_retention_class__retention_days_nonnegative",
        ),
        CheckConstraint(
            ("redaction_after_days IS NULL OR" " redaction_after_days >= 0"),
            name="ck_ops_gov_retention_class__redaction_days_nonnegative",
        ),
        CheckConstraint(
            "purge_grace_days >= 0",
            name="ck_ops_gov_retention_class__purge_grace_days_nonnegative",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_retention_class__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_retention_class__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_gov_retention_class__tenant_code",
        ),
        Index(
            "ix_ops_gov_retention_class__tenant_resource_active",
            "tenant_id",
            "resource_type",
            "is_active",
        ),
        Index(
            "ux_ops_gov_retention_class__tenant_resource_active",
            "tenant_id",
            "resource_type",
            unique=True,
            postgresql_where=sa_text("is_active = true"),
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"RetentionClass(id={self.id!r})"
