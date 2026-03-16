"""Provides an ORM for ACP-owned mixed-scope runtime config profiles."""

__all__ = ["RuntimeConfigProfile"]

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class RuntimeConfigProfile(ModelBase, TenantScopedMixin):
    """ACP-managed mixed-scope runtime config overlays."""

    __tablename__ = "admin_runtime_config_profile"

    category: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    profile_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    settings_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(category)) > 0",
            name="ck_runtime_cfg_profile__category_nonempty",
        ),
        CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_runtime_cfg_profile__profile_key_nonempty",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_runtime_cfg_profile__display_name_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_runtime_cfg_profile__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "category",
            "profile_key",
            name="ux_runtime_cfg_profile__tenant_category_profile",
        ),
        Index(
            "ix_runtime_cfg_profile__tenant_category_active",
            "tenant_id",
            "category",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"RuntimeConfigProfile(id={self.id!r})"
