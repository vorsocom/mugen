"""ORM model for immutable web conversation events."""

__all__ = ["WebConversationEvent"]

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class WebConversationEvent(ModelBase):
    """Durable event stream records for one conversation."""

    __tablename__ = "web_conversation_event"

    conversation_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    payload: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    stream_generation: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    stream_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa_text("1"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_conversation_event_conversation_id_nonempty",
        ),
        CheckConstraint(
            "event_id > 0",
            name="ck_web_conversation_event_event_id_positive",
        ),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_web_conversation_event_event_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(stream_generation)) > 0",
            name="ck_web_conversation_event_stream_generation_nonempty",
        ),
        UniqueConstraint(
            "conversation_id",
            "event_id",
            name="ux_web_conversation_event_conversation_id_event_id",
        ),
        Index(
            "ix_web_conversation_event_conversation_event_id",
            "conversation_id",
            "event_id",
        ),
        Index(
            "ix_web_conversation_event_conversation_created_at",
            "conversation_id",
            "created_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WebConversationEvent(id={self.id!r})"
