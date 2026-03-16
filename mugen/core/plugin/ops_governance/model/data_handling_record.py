"""Provides an ORM for data handling records."""

from __future__ import annotations

__all__ = ["DataHandlingRecord", "DataRequestType", "DataRequestStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String
from sqlalchemy import UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class DataRequestType(str, enum.Enum):
    """Data handling request type values."""

    RETENTION = "retention"
    REDACTION = "redaction"
    ERASURE = "erasure"
    ACCESS = "access"


class DataRequestStatus(str, enum.Enum):
    """Data handling request status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# pylint: disable=too-few-public-methods
class DataHandlingRecord(ModelBase, TenantScopedMixin):
    """An ORM for data handling and redaction/erasure request metadata."""

    __tablename__ = "ops_governance_data_handling_record"

    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    subject_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    subject_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    request_type: Mapped[str] = mapped_column(
        PGENUM(
            DataRequestType,
            name="ops_governance_data_request_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'retention'"),
    )

    request_status: Mapped[str] = mapped_column(
        PGENUM(
            DataRequestStatus,
            name="ops_governance_data_request_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'pending'"),
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=sa_text("now()"),
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    resolution_note: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    handled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    evidence_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    evidence_blob_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    meta: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "retention_policy_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_governance_retention_policy.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_governance_retention_policy.id",
            ),
            name="fkx_ops_gov_data_handling_record__tenant_retention_policy",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "evidence_blob_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.audit_evidence_blob.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.audit_evidence_blob.id",
            ),
            name="fkx_ops_gov_data_handling_record__tenant_evidence_blob",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(subject_namespace)) > 0",
            name="ck_ops_gov_data_handling_record__subject_namespace_nonempty",
        ),
        CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_gov_data_handling_record__subject_ref_nonempty_if_set",
        ),
        CheckConstraint(
            ("resolution_note IS NULL OR" " length(btrim(resolution_note)) > 0"),
            name="ck_ops_gov_data_handling_record__resolution_note_nonempty",
        ),
        CheckConstraint(
            "evidence_ref IS NULL OR length(btrim(evidence_ref)) > 0",
            name="ck_ops_gov_data_handling_record__evidence_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_data_handling_record__tenant_id_id",
        ),
        Index(
            "ix_ops_gov_data_handling_record__tenant_status_requested",
            "tenant_id",
            "request_status",
            "requested_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"DataHandlingRecord(id={self.id!r})"
