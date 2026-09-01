"""Provides the tenant-scoped Service Profile ORM."""

from __future__ import annotations

__all__ = ["ServiceProfile", "ServiceProfileLifecycleStatus"]

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class ServiceProfileLifecycleStatus(str, enum.Enum):
    """Lifecycle states shared by profiles and Subscription assignments."""

    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


# pylint: disable=too-few-public-methods
class ServiceProfile(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """A stable, channel-neutral routable service identity."""

    __tablename__ = "service_profile_service_profile"

    key: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(CITEXT(256), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        PGENUM(
            ServiceProfileLifecycleStatus,
            name="service_profile_lifecycle_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'draft'"),
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(key)) > 0 AND key = btrim(key) AND key = lower(key)",
            name="ck_service_profile__key_nonempty_trimmed",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name = btrim(display_name)",
            name="ck_service_profile__display_name_nonempty_trimmed",
        ),
        CheckConstraint(
            "(status = 'draft' AND activated_at IS NULL AND disabled_at IS NULL) OR "
            "(status = 'active' AND activated_at IS NOT NULL AND disabled_at IS NULL) "
            "OR (status = 'disabled' AND activated_at IS NOT NULL AND "
            "disabled_at IS NOT NULL)",
            name="ck_service_profile__lifecycle_timestamps",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_service_profile__archive_actor",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_service_profile__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "key",
            name="ux_service_profile__tenant_key",
        ),
        Index(
            "ix_service_profile__tenant_status_deleted",
            "tenant_id",
            "status",
            "deleted_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ServiceProfile(id={self.id!r})"
