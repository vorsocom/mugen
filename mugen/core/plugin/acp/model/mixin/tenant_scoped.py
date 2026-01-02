"""Provides an SQLAlchemy declarative mixin for implementing tenant scoping."""

__all__ = ["TenantScopedMixin"]

import uuid

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class TenantScopedMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing tenant scoping."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.admin_tenant.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
