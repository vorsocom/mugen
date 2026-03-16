"""Provides an ORM for export item ledger rows."""

from __future__ import annotations

__all__ = ["ExportItem"]

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class ExportItem(ModelBase, TenantScopedMixin):
    """An ORM for deterministic export item hashes and payload metadata."""

    __tablename__ = "ops_reporting_export_item"

    export_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    item_index: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    resource_type: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    content_hash: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    content_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    meta_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "export_job_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_reporting_export_job.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_reporting_export_job.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_export_item__tenant_export_job",
        ),
        CheckConstraint(
            "item_index >= 0",
            name="ck_ops_reporting_export_item__item_index_nonnegative",
        ),
        CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_reporting_export_item__resource_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_ops_reporting_export_item__content_hash_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(content_json) = 'object'",
            name="ck_ops_reporting_export_item__content_json_object",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_export_item__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "export_job_id",
            "item_index",
            name="ux_ops_reporting_export_item__tenant_job_item_index",
        ),
        Index(
            "ix_ops_reporting_export_item__tenant_job_item",
            "tenant_id",
            "export_job_id",
            "item_index",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ExportItem(id={self.id!r})"
