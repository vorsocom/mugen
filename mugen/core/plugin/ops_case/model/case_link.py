"""Provides an ORM for generic case-linked entities."""

from __future__ import annotations

__all__ = ["CaseLink"]

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class CaseLink(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for generic related-object references linked to a case."""

    __tablename__ = "ops_case_case_link"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    link_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    target_namespace: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    target_type: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    target_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    target_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    target_display: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    relationship_kind: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'related'"),
        index=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    case: Mapped["Case"] = relationship(  # type: ignore
        back_populates="links",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            (f"{CORE_SCHEMA_TOKEN}.ops_case_case.tenant_id", f"{CORE_SCHEMA_TOKEN}.ops_case_case.id"),
            name="fkx_ops_case_case_link__tenant_case",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(link_type)) > 0",
            name="ck_ops_case_case_link__link_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(target_type)) > 0",
            name="ck_ops_case_case_link__target_type_nonempty",
        ),
        CheckConstraint(
            "target_ref IS NULL OR length(btrim(target_ref)) > 0",
            name="ck_ops_case_case_link__target_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "relationship_kind IS NULL OR length(btrim(relationship_kind)) > 0",
            name="ck_ops_case_case_link__relationship_kind_nonempty_if_set",
        ),
        CheckConstraint(
            "target_id IS NOT NULL OR target_ref IS NOT NULL",
            name="ck_ops_case_case_link__target_reference_required",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_case_case_link__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_link__tenant_id_id",
        ),
        Index(
            "ix_ops_case_case_link__tenant_case_target",
            "tenant_id",
            "case_id",
            "target_type",
            "target_id",
            "target_ref",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"CaseLink(id={self.id!r})"
