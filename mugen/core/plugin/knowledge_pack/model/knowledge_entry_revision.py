"""Provides an ORM for knowledge entry revisions and scope tags."""

from __future__ import annotations

__all__ = ["KnowledgeEntryRevision"]

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.plugin.knowledge_pack.model.knowledge_pack_version import (
    KnowledgePublicationStatus,
)
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.knowledge_pack.model.knowledge_entry import KnowledgeEntry
    from mugen.core.plugin.knowledge_pack.model.knowledge_scope import KnowledgeScope


# pylint: disable=too-few-public-methods
class KnowledgeEntryRevision(ModelBase, TenantScopedMixin):
    """An ORM for versioned knowledge entry revisions."""

    __tablename__ = "knowledge_pack_knowledge_entry_revision"

    knowledge_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    knowledge_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    revision_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            KnowledgePublicationStatus,
            name="knowledge_pack_publication_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=False,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("draft"),
    )

    body: Mapped[str | None] = mapped_column(
        String(8192),
        nullable=True,
    )

    body_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    channel: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    locale: Mapped[str | None] = mapped_column(
        CITEXT(16),
        nullable=True,
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        CITEXT(64),
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

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    knowledge_entry: Mapped["KnowledgeEntry"] = relationship(  # type: ignore
        back_populates="revisions",
    )

    scopes: Mapped[list["KnowledgeScope"]] = relationship(  # type: ignore
        back_populates="knowledge_entry_revision",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry.id",
            ),
            name="fkx_knowledge_entry_revision__tenant_entry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_entry_revision__tenant_pack_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_knowledge_entry_revision__revision_number_positive",
        ),
        CheckConstraint(
            "body IS NOT NULL OR body_json IS NOT NULL",
            name="ck_knowledge_entry_revision__content_required",
        ),
        CheckConstraint(
            "body IS NULL OR length(btrim(body)) > 0",
            name="ck_knowledge_entry_revision__body_nonempty_if_set",
        ),
        CheckConstraint(
            "channel IS NULL OR length(btrim(channel)) > 0",
            name="ck_knowledge_entry_revision__channel_nonempty_if_set",
        ),
        CheckConstraint(
            "locale IS NULL OR length(btrim(locale)) > 0",
            name="ck_knowledge_entry_revision__locale_nonempty_if_set",
        ),
        CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_knowledge_entry_revision__category_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_entry_revision__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "knowledge_entry_id",
            "revision_number",
            name="ux_knowledge_entry_revision__tenant_entry_revision",
        ),
        Index(
            "ix_knowledge_entry_revision__tenant_version_status",
            "tenant_id",
            "knowledge_pack_version_id",
            "status",
        ),
        Index(
            "ix_knowledge_entry_revision__tenant_scope_status",
            "tenant_id",
            "channel",
            "locale",
            "category",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgeEntryRevision(id={self.id!r})"
