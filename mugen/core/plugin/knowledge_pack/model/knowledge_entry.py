"""Provides an ORM for versioned knowledge entries."""

from __future__ import annotations

__all__ = ["KnowledgeEntry"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
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
    from mugen.core.plugin.knowledge_pack.model.knowledge_pack import KnowledgePack
    from mugen.core.plugin.knowledge_pack.model.knowledge_pack_version import (
        KnowledgePackVersion,
    )


# pylint: disable=too-few-public-methods
class KnowledgeEntry(ModelBase, TenantScopedMixin):
    """An ORM for knowledge entries within a specific knowledge pack version."""

    __tablename__ = "knowledge_pack_knowledge_entry"

    knowledge_pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    knowledge_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    entry_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    summary: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
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

    knowledge_pack: Mapped["KnowledgePack"] = relationship(
        foreign_keys=[knowledge_pack_id],
    )

    knowledge_pack_version: Mapped["KnowledgePackVersion"] = relationship(
        back_populates="entries", foreign_keys=[knowledge_pack_version_id]
    )

    revisions: Mapped[list["KnowledgeEntryRevision"]] = relationship(  # type: ignore
        back_populates="knowledge_entry",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_entry__tenant_pack",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_entry__tenant_pack_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(entry_key)) > 0",
            name="ck_knowledge_entry__entry_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_knowledge_entry__title_nonempty",
        ),
        CheckConstraint(
            "summary IS NULL OR length(btrim(summary)) > 0",
            name="ck_knowledge_entry__summary_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_entry__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "knowledge_pack_version_id",
            "entry_key",
            name="ux_knowledge_entry__tenant_version_entry_key",
        ),
        Index(
            "ix_knowledge_entry__tenant_version_active",
            "tenant_id",
            "knowledge_pack_version_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"KnowledgeEntry(id={self.id!r})"
