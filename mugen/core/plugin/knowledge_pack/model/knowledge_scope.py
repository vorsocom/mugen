"""Provides an ORM for scoped knowledge retrieval constraints."""

from __future__ import annotations

__all__ = ["KnowledgeScope"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.knowledge_pack.model.knowledge_entry_revision import (
        KnowledgeEntryRevision,
    )


# pylint: disable=too-few-public-methods
class KnowledgeScope(ModelBase, TenantScopedMixin):
    """An ORM for retrieval scope constraints tied to entry revisions."""

    __tablename__ = "knowledge_pack_knowledge_scope"

    knowledge_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    knowledge_entry_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
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

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        server_default=sa_text("true"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    knowledge_entry_revision: Mapped["KnowledgeEntryRevision"] = relationship(
        back_populates="scopes"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_scope__tenant_pack_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_revision_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry_revision.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_entry_revision.id",
            ),
            name="fkx_knowledge_scope__tenant_entry_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "channel IS NULL OR length(btrim(channel)) > 0",
            name="ck_knowledge_scope__channel_nonempty_if_set",
        ),
        CheckConstraint(
            "locale IS NULL OR length(btrim(locale)) > 0",
            name="ck_knowledge_scope__locale_nonempty_if_set",
        ),
        CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_knowledge_scope__category_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_scope__tenant_id_id",
        ),
        Index(
            "ix_knowledge_scope__tenant_scope_active",
            "tenant_id",
            "channel",
            "locale",
            "category",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgeScope(id={self.id!r})"
