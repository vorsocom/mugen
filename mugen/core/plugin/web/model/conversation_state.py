"""ORM model for durable web conversation stream state."""

__all__ = ["WebConversationState"]

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class WebConversationState(ModelBase):
    """Per-conversation stream state and ownership metadata."""

    __tablename__ = "web_conversation_state"

    conversation_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    owner_user_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    stream_generation: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    stream_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa_text("1"),
    )

    next_event_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_conversation_state_conversation_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(owner_user_id)) > 0",
            name="ck_web_conversation_state_owner_user_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(stream_generation)) > 0",
            name="ck_web_conversation_state_stream_generation_nonempty",
        ),
        CheckConstraint(
            "next_event_id > 0",
            name="ck_web_conversation_state_next_event_id_positive",
        ),
        UniqueConstraint(
            "conversation_id",
            name="ux_web_conversation_state_conversation_id",
        ),
        Index(
            "ix_web_conversation_state_owner_conversation",
            "owner_user_id",
            "conversation_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WebConversationState(id={self.id!r})"
