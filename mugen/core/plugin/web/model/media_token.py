"""ORM model for web media download tokens."""

__all__ = ["WebMediaToken"]

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class WebMediaToken(ModelBase):
    """Durable media token records for authenticated download resolution."""

    __tablename__ = "web_media_token"

    token: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    owner_user_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    file_path: Mapped[str] = mapped_column(
        CITEXT(2048),
        nullable=False,
    )

    mime_type: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    filename: Mapped[str | None] = mapped_column(
        CITEXT(512),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(token)) > 0",
            name="ck_web_media_token_token_nonempty",
        ),
        CheckConstraint(
            "length(btrim(owner_user_id)) > 0",
            name="ck_web_media_token_owner_user_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_media_token_conversation_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(file_path)) > 0",
            name="ck_web_media_token_file_path_nonempty",
        ),
        UniqueConstraint(
            "token",
            name="ux_web_media_token_token",
        ),
        Index(
            "ix_web_media_token_owner_expires",
            "owner_user_id",
            "expires_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WebMediaToken(id={self.id!r})"
