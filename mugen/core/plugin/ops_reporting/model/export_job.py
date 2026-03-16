"""Provides an ORM for export job metadata."""

from __future__ import annotations

__all__ = ["ExportJob", "ExportJobStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class ExportJobStatus(str, enum.Enum):
    """Lifecycle status for export jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# pylint: disable=too-few-public-methods
class ExportJob(ModelBase, TenantScopedMixin):
    """An ORM for deterministic export build and verification jobs."""

    __tablename__ = "ops_reporting_export_job"

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    export_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    spec_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    default_sign: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    default_signature_key_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            ExportJobStatus,
            name="ops_reporting_export_job_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("'queued'"),
        index=True,
    )

    manifest_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    manifest_hash: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    signature_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    export_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    policy_decision_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_reporting_export_job__trace_id_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(export_type)) > 0",
            name="ck_ops_reporting_export_job__export_type_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(spec_json) = 'object'",
            name="ck_ops_reporting_export_job__spec_json_object",
        ),
        CheckConstraint(
            (
                "default_signature_key_id IS NULL OR "
                "length(btrim(default_signature_key_id)) > 0"
            ),
            name="ck_ops_reporting_export_job__default_sig_key_id_nonempty",
        ),
        CheckConstraint(
            "manifest_hash IS NULL OR length(btrim(manifest_hash)) > 0",
            name="ck_ops_reporting_export_job__manifest_hash_nonempty_if_set",
        ),
        CheckConstraint(
            "export_ref IS NULL OR length(btrim(export_ref)) > 0",
            name="ck_ops_reporting_export_job__export_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "error_message IS NULL OR length(btrim(error_message)) > 0",
            name="ck_ops_reporting_export_job__error_message_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_export_job__tenant_id_id",
        ),
        Index(
            "ix_ops_reporting_export_job__tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_ops_reporting_export_job__tenant_trace",
            "tenant_id",
            "trace_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ExportJob(id={self.id!r})"
