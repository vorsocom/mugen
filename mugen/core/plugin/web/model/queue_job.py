"""ORM model for durable web inbound processing jobs."""

__all__ = ["WebQueueJob"]

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class WebQueueJob(ModelBase):
    """Durable queue state with lease-aware job ownership fields."""

    __tablename__ = "web_queue_job"

    job_id: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    sender: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    message_type: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    payload: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
        server_default=sa_text("'pending'"),
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

    error_message: Mapped[str | None] = mapped_column(
        CITEXT(2048),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    client_message_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(job_id)) > 0",
            name="ck_web_queue_job_job_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_queue_job_conversation_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(sender)) > 0",
            name="ck_web_queue_job_sender_nonempty",
        ),
        CheckConstraint(
            "length(btrim(message_type)) > 0",
            name="ck_web_queue_job_message_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_web_queue_job_status_nonempty",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_web_queue_job_attempts_nonnegative",
        ),
        UniqueConstraint(
            "job_id",
            name="ux_web_queue_job_job_id",
        ),
        Index(
            "ix_web_queue_job_status_lease",
            "status",
            "lease_expires_at",
        ),
        Index(
            "ix_web_queue_job_conversation_created",
            "conversation_id",
            "created_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WebQueueJob(id={self.id!r})"
