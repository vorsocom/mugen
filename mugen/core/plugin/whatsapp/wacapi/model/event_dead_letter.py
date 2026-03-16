"""Provides an ORM for WhatsApp webhook dead-letter events."""

__all__ = ["WhatsAppWACAPIEventDeadLetter"]

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class WhatsAppWACAPIEventDeadLetter(ModelBase):
    """An ORM for persisted WhatsApp webhook processing failures."""

    __tablename__ = "whatsapp_wacapi_event_dead_letter"

    event_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    dedupe_key: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    payload: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    reason_code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        CITEXT(1024),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
        server_default=sa_text("'queued'"),
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa_text("1"),
    )

    first_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_wacapi_dead_letter_event_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_wacapi_dead_letter_reason_nonempty",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_wacapi_dead_letter_status_nonempty",
        ),
        CheckConstraint(
            "attempts > 0",
            name="ck_wacapi_dead_letter_attempts_positive",
        ),
        Index(
            "ix_wacapi_dead_letter_status_failed_at",
            "status",
            "last_failed_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WhatsAppWACAPIEventDeadLetter(id={self.id!r})"
