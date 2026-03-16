"""Provides an ORM for Signal receive event dedupe records."""

__all__ = ["SignalRestAPIEventDedup"]

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class SignalRestAPIEventDedup(ModelBase):
    """An ORM for durable Signal event dedupe keys."""

    __tablename__ = "signal_restapi_event_dedup"

    event_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    dedupe_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    event_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_signal_restapi_event_dedup_event_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_signal_restapi_event_dedup_key_nonempty",
        ),
        UniqueConstraint(
            "event_type",
            "dedupe_key",
            name="ux_signal_restapi_event_dedup_event_type_key",
        ),
        Index(
            "ix_signal_restapi_event_dedup_expiry",
            "event_type",
            "expires_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SignalRestAPIEventDedup(id={self.id!r})"
