"""ORM for staged messaging ingress events."""

__all__ = ["MessagingIngressEventRecord"]

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, Integer
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class MessagingIngressEventRecord(ModelBase):
    """Durable inbox row for one canonical inbound messaging event."""

    __tablename__ = "messaging_ingress_event"

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa_text("1"),
    )

    platform: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    client_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    ipc_command: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    source_mode: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    event_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    dedupe_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    identifier_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    identifier_value: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    room_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    sender: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    payload: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    provider_context: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
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
        server_default=sa_text("0"),
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        CITEXT(1024),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_msg_ingress_event_version_positive"),
        CheckConstraint("length(btrim(platform)) > 0", name="ck_msg_ingress_event_platform_nonempty"),
        CheckConstraint(
            "length(btrim(ipc_command)) > 0",
            name="ck_msg_ingress_event_ipc_command_nonempty",
        ),
        CheckConstraint(
            "length(btrim(source_mode)) > 0",
            name="ck_msg_ingress_event_source_mode_nonempty",
        ),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_msg_ingress_event_event_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_msg_ingress_event_dedupe_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(identifier_type)) > 0",
            name="ck_msg_ingress_event_identifier_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_msg_ingress_event_status_nonempty",
        ),
        CheckConstraint("attempts >= 0", name="ck_msg_ingress_event_attempts_nonnegative"),
        Index(
            "ix_msg_ingress_event_status_lease",
            "status",
            "lease_expires_at",
            "received_at",
        ),
        Index(
            "ix_msg_ingress_event_platform_profile_status",
            "platform",
            "client_profile_id",
            "status",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MessagingIngressEventRecord(id={self.id!r})"
