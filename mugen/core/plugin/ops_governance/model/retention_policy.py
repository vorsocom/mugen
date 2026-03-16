"""Provides an ORM for retention policy metadata."""

from __future__ import annotations

__all__ = ["RetentionPolicy", "RetentionActionMode"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String
from sqlalchemy import UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class RetentionActionMode(str, enum.Enum):
    """Retention action mode values."""

    MARK = "mark"
    REDACT = "redact"
    ERASE = "erase"
    ARCHIVE = "archive"


# pylint: disable=too-few-public-methods
class RetentionPolicy(ModelBase, TenantScopedMixin):
    """An ORM for retention/redaction policy metadata."""

    __tablename__ = "ops_governance_retention_policy"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    target_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    target_entity: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
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

    legal_hold_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    action_mode: Mapped[str] = mapped_column(
        PGENUM(
            RetentionActionMode,
            name="ops_governance_retention_action_mode",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("'mark'"),
    )

    downstream_job_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    last_action_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_action_type: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    last_action_status: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
    )

    last_action_note: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    last_action_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_retention_policy__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_retention_policy__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(target_namespace)) > 0",
            name="ck_ops_gov_retention_policy__target_namespace_nonempty",
        ),
        CheckConstraint(
            "target_entity IS NULL OR length(btrim(target_entity)) > 0",
            name="ck_ops_gov_retention_policy__target_entity_nonempty_if_set",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_retention_policy__description_nonempty_if_set",
        ),
        CheckConstraint(
            "retention_days >= 0",
            name="ck_ops_gov_retention_policy__retention_days_nonnegative",
        ),
        CheckConstraint(
            (
                "redaction_after_days IS NULL OR"
                " redaction_after_days >= 0"
            ),
            name="ck_ops_gov_retention_policy__redaction_days_nonnegative",
        ),
        CheckConstraint(
            (
                "downstream_job_ref IS NULL OR"
                " length(btrim(downstream_job_ref)) > 0"
            ),
            name="ck_ops_gov_retention_policy__downstream_job_ref_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "last_action_type IS NULL OR"
                " length(btrim(last_action_type)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_type_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "last_action_status IS NULL OR"
                " length(btrim(last_action_status)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_status_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "last_action_note IS NULL OR"
                " length(btrim(last_action_note)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_note_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_retention_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_gov_retention_policy__tenant_code",
        ),
        Index(
            "ix_ops_gov_retention_policy__tenant_target_active",
            "tenant_id",
            "target_namespace",
            "target_entity",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"RetentionPolicy(id={self.id!r})"
