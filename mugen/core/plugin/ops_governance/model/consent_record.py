"""Provides an ORM for consent records."""

from __future__ import annotations

__all__ = ["ConsentRecord", "ConsentStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class ConsentStatus(str, enum.Enum):
    """Consent record status values."""

    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


# pylint: disable=too-few-public-methods
class ConsentRecord(ModelBase, TenantScopedMixin):
    """An ORM for append-only consent grant/withdrawal records."""

    __tablename__ = "ops_governance_consent_record"

    subject_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    controller_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    purpose: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    scope: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    legal_basis: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            ConsentStatus,
            name="ops_governance_consent_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'granted'"),
    )

    effective_at: Mapped[datetime] = mapped_column(
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

    source_consent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    withdrawn_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    withdrawal_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(controller_namespace)) > 0",
            name="ck_ops_gov_consent_record__controller_namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(purpose)) > 0",
            name="ck_ops_gov_consent_record__purpose_nonempty",
        ),
        CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_ops_gov_consent_record__scope_nonempty",
        ),
        CheckConstraint(
            "legal_basis IS NULL OR length(btrim(legal_basis)) > 0",
            name="ck_ops_gov_consent_record__legal_basis_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "withdrawal_reason IS NULL OR"
                " length(btrim(withdrawal_reason)) > 0"
            ),
            name="ck_ops_gov_consent_record__withdrawal_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_consent_record__tenant_id_id",
        ),
        Index(
            "ix_ops_gov_consent_record__tenant_subject_effective",
            "tenant_id",
            "subject_user_id",
            "effective_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ConsentRecord(id={self.id!r})"
