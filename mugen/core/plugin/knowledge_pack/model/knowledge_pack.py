"""Provides an ORM for knowledge packs."""

from __future__ import annotations

__all__ = ["KnowledgePack"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
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

if TYPE_CHECKING:
    from mugen.core.plugin.knowledge_pack.model.knowledge_pack_version import (
        KnowledgePackVersion,
    )


# pylint: disable=too-few-public-methods
class KnowledgePack(ModelBase, TenantScopedMixin):
    """An ORM for generic knowledge packs."""

    __tablename__ = "knowledge_pack_knowledge_pack"

    key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        server_default=sa_text("true"),
    )

    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.knowledge_pack_knowledge_pack_version.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    current_version: Mapped["KnowledgePackVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )

    versions: Mapped[list["KnowledgePackVersion"]] = relationship(  # type: ignore
        back_populates="knowledge_pack",
        cascade="save-update, merge",
        foreign_keys="KnowledgePackVersion.knowledge_pack_id",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_knowledge_pack_pack__key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_knowledge_pack_pack__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_knowledge_pack_pack__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_pack_pack__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "key",
            name="ux_knowledge_pack_pack__tenant_key",
        ),
        Index(
            "ix_knowledge_pack_pack__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"KnowledgePack(id={self.id!r})"
