"""Provides an ORM for knowledge pack versions and publish states."""

from __future__ import annotations

__all__ = ["KnowledgePackVersion", "KnowledgePublicationStatus"]

from datetime import datetime
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.knowledge_pack.model.knowledge_entry import KnowledgeEntry
    from mugen.core.plugin.knowledge_pack.model.knowledge_pack import KnowledgePack


class KnowledgePublicationStatus(str, enum.Enum):
    """Knowledge publish workflow states."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# pylint: disable=too-few-public-methods
class KnowledgePackVersion(ModelBase, TenantScopedMixin):
    """An ORM for versioned knowledge packs."""

    __tablename__ = "knowledge_pack_knowledge_pack_version"

    knowledge_pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            KnowledgePublicationStatus,
            name="knowledge_pack_publication_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("draft"),
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    rollback_of_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    knowledge_pack: Mapped["KnowledgePack"] = relationship(  # type: ignore
        back_populates="versions",
        foreign_keys=[knowledge_pack_id],
    )

    entries: Mapped[list["KnowledgeEntry"]] = relationship(  # type: ignore
        back_populates="knowledge_pack_version",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_pack_version__tenant_pack",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_knowledge_pack_version__version_number_positive",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_knowledge_pack_version__note_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_pack_version__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "knowledge_pack_id",
            "version_number",
            name="ux_knowledge_pack_version__tenant_pack_version",
        ),
        Index(
            "ix_knowledge_pack_version__tenant_pack_status",
            "tenant_id",
            "knowledge_pack_id",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgePackVersion(id={self.id!r})"
