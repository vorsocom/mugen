"""ORM for messaging ingress dedupe keys."""

__all__ = ["MessagingIngressDedupRecord"]

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class MessagingIngressDedupRecord(ModelBase):
    """Durable dedupe record for canonical messaging ingress events."""

    __tablename__ = "messaging_ingress_dedup"

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
        CheckConstraint("length(btrim(platform)) > 0", name="ck_msg_ingress_dedup_platform_nonempty"),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_msg_ingress_dedup_event_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_msg_ingress_dedup_key_nonempty",
        ),
        UniqueConstraint(
            "platform",
            "client_profile_id",
            "dedupe_key",
            name="ux_msg_ingress_dedup_platform_profile_key",
        ),
        Index(
            "ix_msg_ingress_dedup_expiry",
            "platform",
            "client_profile_id",
            "expires_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MessagingIngressDedupRecord(id={self.id!r})"
