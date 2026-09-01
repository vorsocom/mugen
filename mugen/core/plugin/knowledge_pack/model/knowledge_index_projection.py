"""Provides the durable Knowledge Pack search projection ORM."""

from __future__ import annotations

__all__ = ["KnowledgeIndexProjection", "KnowledgeProjectionStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class KnowledgeProjectionStatus(str, enum.Enum):
    """Durable projection attempt lifecycle states."""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


# pylint: disable=too-few-public-methods
class KnowledgeIndexProjection(ModelBase, TenantScopedMixin):
    """A durable projection attempt and queue lease for one provider target."""

    __tablename__ = "knowledge_pack_knowledge_index_projection"

    knowledge_pack_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    knowledge_pack_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    target_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    projection_schema_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    operation: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        PGENUM(
            KnowledgeProjectionStatus,
            name="knowledge_pack_projection_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("queued"),
    )

    document_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    attempt_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    max_attempts: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("3"),
    )

    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    failure_detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    is_current_ready: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
    )

    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_index_projection__tenant_pack",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_index_projection__tenant_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "operation IN ('publish', 'reindex', 'rollback', 'cleanup')",
            name="ck_knowledge_index_projection__operation",
        ),
        CheckConstraint(
            "projection_schema_version > 0",
            name="ck_knowledge_index_projection__schema_version_positive",
        ),
        CheckConstraint(
            "document_count >= 0 AND attempt_count >= 0 AND max_attempts > 0",
            name="ck_knowledge_index_projection__counts_nonnegative",
        ),
        CheckConstraint(
            "length(target_fingerprint) = 64 AND length(content_checksum) = 64",
            name="ck_knowledge_index_projection__checksums",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_index_projection__tenant_id_id",
        ),
        Index(
            "ix_knowledge_index_projection__tenant_version_target",
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
        ),
        Index(
            "ix_knowledge_index_projection__queue_lease",
            "status",
            "lease_expires_at",
            "requested_at",
        ),
        Index(
            "ux_knowledge_index_projection__active_attempt",
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
            unique=True,
            postgresql_where=sa_text("status IN ('queued', 'processing')"),
        ),
        Index(
            "ux_knowledge_index_projection__current_ready",
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
            unique=True,
            postgresql_where=sa_text("is_current_ready"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgeIndexProjection(id={self.id!r})"
