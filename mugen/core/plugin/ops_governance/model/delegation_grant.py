"""Provides an ORM for delegation grant records."""

from __future__ import annotations

__all__ = ["DelegationGrant", "DelegationStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class DelegationStatus(str, enum.Enum):
    """Delegation status values."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# pylint: disable=too-few-public-methods
class DelegationGrant(ModelBase, TenantScopedMixin):
    """An ORM for append-only delegation grant/revocation records."""

    __tablename__ = "ops_governance_delegation_grant"

    principal_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    delegate_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    scope: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    purpose: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            DelegationStatus,
            name="ops_governance_delegation_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    source_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
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

    revocation_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "principal_user_id <> delegate_user_id",
            name="ck_ops_gov_delegation_grant__principal_delegate_distinct",
        ),
        CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_ops_gov_delegation_grant__scope_nonempty",
        ),
        CheckConstraint(
            "purpose IS NULL OR length(btrim(purpose)) > 0",
            name="ck_ops_gov_delegation_grant__purpose_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "revocation_reason IS NULL OR"
                " length(btrim(revocation_reason)) > 0"
            ),
            name="ck_ops_gov_delegation_grant__revocation_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_delegation_grant__tenant_id_id",
        ),
        Index(
            "ix_ops_gov_delegation_grant__tenant_principal_delegate_status",
            "tenant_id",
            "principal_user_id",
            "delegate_user_id",
            "status",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"DelegationGrant(id={self.id!r})"
