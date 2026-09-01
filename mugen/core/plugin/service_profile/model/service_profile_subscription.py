"""Provides the Service Profile Billing Subscription assignment ORM."""

from __future__ import annotations

__all__ = ["ServiceProfileSubscription"]

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.plugin.service_profile.model.service_profile import (
    ServiceProfileLifecycleStatus,
)
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class ServiceProfileSubscription(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """A commercial allocation of one exact Subscription to one profile."""

    __tablename__ = "service_profile_subscription"

    service_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    billing_subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    product_code: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
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
        ForeignKeyConstraint(
            ("tenant_id", "service_profile_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.service_profile_service_profile.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.service_profile_service_profile.id",
            ),
            name="fkx_service_profile_subscription__tenant_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "billing_subscription_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.billing_subscription.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.billing_subscription.id",
            ),
            name="fkx_service_profile_subscription__tenant_subscription",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "product_code IS NULL OR (length(btrim(product_code)) > 0 AND "
            "product_code = btrim(product_code) AND product_code = "
            "lower(product_code))",
            name="ck_service_profile_subscription__product_code",
        ),
        CheckConstraint(
            "(status = 'draft' AND product_code IS NULL AND activated_at IS NULL "
            "AND disabled_at IS NULL) OR (status = 'active' AND "
            "product_code IS NOT NULL AND activated_at IS NOT NULL AND "
            "disabled_at IS NULL) OR (status = 'disabled' AND "
            "product_code IS NOT NULL AND activated_at IS NOT NULL AND "
            "disabled_at IS NOT NULL)",
            name="ck_service_profile_subscription__lifecycle",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_service_profile_subscription__archive_actor",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_service_profile_subscription__tenant_id_id",
        ),
        Index(
            "ux_service_profile_subscription__active_subscription",
            "tenant_id",
            "billing_subscription_id",
            unique=True,
            postgresql_where=sa_text("status = 'active' AND deleted_at IS NULL"),
        ),
        Index(
            "ux_service_profile_subscription__active_profile_product",
            "tenant_id",
            "service_profile_id",
            "product_code",
            unique=True,
            postgresql_where=sa_text("status = 'active' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_service_profile_subscription__tenant_status_deleted",
            "tenant_id",
            "status",
            "deleted_at",
        ),
        Index(
            "ix_service_profile_subscription__tenant_profile_status",
            "tenant_id",
            "service_profile_id",
            "status",
        ),
        Index(
            "ix_service_profile_subscription__tenant_product",
            "tenant_id",
            "product_code",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ServiceProfileSubscription(id={self.id!r})"
