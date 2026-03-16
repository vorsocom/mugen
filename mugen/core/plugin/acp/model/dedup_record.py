"""Provides an ORM for dedup ledger records."""

__all__ = ["DedupRecord"]

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, Uuid

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class DedupRecordStatus(str, enum.Enum):
    """Dedup ledger status enum values."""

    IN_PROGRESS = "in_progress"

    SUCCEEDED = "succeeded"

    FAILED = "failed"


# pylint: disable=too-few-public-methods
class DedupRecord(ModelBase):
    """An ORM for ACP shared idempotency ledger records."""

    __tablename__ = "admin_dedup_record"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    scope: Mapped[str] = mapped_column(CITEXT(200), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(CITEXT(256), nullable=False)

    request_hash: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)

    status: Mapped[str] = mapped_column(
        PGENUM(
            DedupRecordStatus,
            name="admin_dedup_record_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'in_progress'"),
    )

    result_ref: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)

    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    response_payload: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    error_code: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)

    error_message: Mapped[str | None] = mapped_column(CITEXT(1024), nullable=True)

    owner_instance: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_dedup_record__scope_nonempty",
        ),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_dedup_record__idempotency_key_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "scope",
            "idempotency_key",
            name="ux_dedup_record__tenant_scope_key",
        ),
        Index(
            "ix_dedup_record__tenant_scope_expires",
            "tenant_id",
            "scope",
            "expires_at",
        ),
        Index(
            "ix_dedup_record__status_lease_expires",
            "status",
            "lease_expires_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"DedupRecord(id={self.id!r})"
