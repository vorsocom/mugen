"""Provides an ORM for knowledge governance approval records."""

from __future__ import annotations

__all__ = ["KnowledgeApproval", "KnowledgeApprovalAction"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
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


class KnowledgeApprovalAction(str, enum.Enum):
    """Governance actions recorded for knowledge pack approvals."""

    SUBMIT_FOR_REVIEW = "submit_for_review"
    APPROVE = "approve"
    REJECT = "reject"
    PUBLISH = "publish"
    ARCHIVE = "archive"
    ROLLBACK_VERSION = "rollback_version"


# pylint: disable=too-few-public-methods
class KnowledgeApproval(ModelBase, TenantScopedMixin):
    """An ORM for knowledge governance approval records."""

    __tablename__ = "knowledge_pack_knowledge_approval"

    knowledge_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    knowledge_entry_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        PGENUM(
            KnowledgeApprovalAction,
            name="knowledge_pack_approval_action",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=sa_text("now()"),
    )

    note: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_approval__tenant_pack_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_revision_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry_revision.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry_revision.id",
            ),
            name="fkx_knowledge_approval__tenant_entry_revision",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_knowledge_approval__note_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_approval__tenant_id_id",
        ),
        Index(
            "ix_knowledge_approval__tenant_version_occurred",
            "tenant_id",
            "knowledge_pack_version_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgeApproval(id={self.id!r})"
