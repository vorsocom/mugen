"""Provides an ORM for report snapshot records."""

from __future__ import annotations

__all__ = ["ReportSnapshot", "ReportSnapshotStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class ReportSnapshotStatus(str, enum.Enum):
    """Lifecycle status for generated report snapshots."""

    DRAFT = "draft"
    GENERATED = "generated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# pylint: disable=too-few-public-methods
class ReportSnapshot(ModelBase, TenantScopedMixin):
    """An ORM for point-in-time report snapshots."""

    __tablename__ = "ops_reporting_report_snapshot"

    report_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    metric_codes: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            ReportSnapshotStatus,
            name="ops_reporting_snapshot_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("'draft'"),
        index=True,
    )

    window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    scope_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        server_default=sa_text("'__all__'"),
        index=True,
    )

    summary_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "report_definition_id"],
            [
                "mugen.ops_reporting_report_definition.tenant_id",
                "mugen.ops_reporting_report_definition.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_reporting_report_snapshot__tenant_report_definition",
        ),
        CheckConstraint(
            (
                "window_start IS NULL OR window_end IS NULL OR"
                " window_end > window_start"
            ),
            name="ck_ops_reporting_report_snapshot__window_bounds",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_report_snapshot__scope_key_nonempty",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_reporting_report_snapshot__note_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "report_definition_id IS NOT NULL OR metric_codes IS NOT NULL"
            ),
            name="ck_ops_reporting_report_snapshot__metric_source_required",
        ),
        CheckConstraint(
            "metric_codes IS NULL OR jsonb_typeof(metric_codes) = 'array'",
            name="ck_ops_reporting_report_snapshot__metric_codes_array",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_report_snapshot__tenant_id_id",
        ),
        Index(
            "ix_ops_reporting_report_snapshot__tenant_status_generated",
            "tenant_id",
            "status",
            "generated_at",
        ),
        Index(
            "ix_ops_reporting_report_snapshot__tenant_window",
            "tenant_id",
            "window_start",
            "window_end",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ReportSnapshot(id={self.id!r})"
