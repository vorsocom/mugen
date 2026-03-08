"""ORM for messaging ingress checkpoints."""

__all__ = ["MessagingIngressCheckpointRecord"]

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class MessagingIngressCheckpointRecord(ModelBase):
    """Shared checkpoint row for durable ingress transports."""

    __tablename__ = "messaging_ingress_checkpoint"

    platform: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    runtime_profile_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    checkpoint_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    checkpoint_value: Mapped[str] = mapped_column(
        CITEXT(512),
        nullable=False,
    )

    provider_context: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_msg_ingress_checkpoint_platform_nonempty",
        ),
        CheckConstraint(
            "length(btrim(runtime_profile_key)) > 0",
            name="ck_msg_ingress_checkpoint_runtime_profile_nonempty",
        ),
        CheckConstraint(
            "length(btrim(checkpoint_key)) > 0",
            name="ck_msg_ingress_checkpoint_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(checkpoint_value)) > 0",
            name="ck_msg_ingress_checkpoint_value_nonempty",
        ),
        UniqueConstraint(
            "platform",
            "runtime_profile_key",
            "checkpoint_key",
            name="ux_msg_ingress_checkpoint_platform_profile_key",
        ),
        Index(
            "ix_msg_ingress_checkpoint_platform_profile",
            "platform",
            "runtime_profile_key",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MessagingIngressCheckpointRecord(id={self.id!r})"
