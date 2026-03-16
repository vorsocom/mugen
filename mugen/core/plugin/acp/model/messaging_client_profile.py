"""Provides an ORM for ACP-owned messaging client profiles."""

__all__ = ["MessagingClientProfile"]

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class MessagingClientProfile(ModelBase, TenantScopedMixin):
    """ACP-managed messaging platform client profile metadata."""

    __tablename__ = "admin_messaging_client_profile"

    platform_key: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    profile_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    secret_refs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    path_token: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    recipient_user_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    account_number: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    phone_number_id: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    provider: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(platform_key)) > 0",
            name="ck_msg_client_profile__platform_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_msg_client_profile__profile_key_nonempty",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_msg_client_profile__display_name_nonempty_if_set",
        ),
        CheckConstraint(
            "path_token IS NULL OR length(btrim(path_token)) > 0",
            name="ck_msg_client_profile__path_token_nonempty_if_set",
        ),
        CheckConstraint(
            "recipient_user_id IS NULL OR length(btrim(recipient_user_id)) > 0",
            name="ck_msg_client_profile__recipient_user_id_nonempty_if_set",
        ),
        CheckConstraint(
            "account_number IS NULL OR length(btrim(account_number)) > 0",
            name="ck_msg_client_profile__account_number_nonempty_if_set",
        ),
        CheckConstraint(
            "phone_number_id IS NULL OR length(btrim(phone_number_id)) > 0",
            name="ck_msg_client_profile__phone_number_id_nonempty_if_set",
        ),
        CheckConstraint(
            "provider IS NULL OR length(btrim(provider)) > 0",
            name="ck_msg_client_profile__provider_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_msg_client_profile__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "platform_key",
            "profile_key",
            name="ux_msg_client_profile__tenant_platform_profile",
        ),
        Index(
            "ix_msg_client_profile__tenant_platform_active",
            "tenant_id",
            "platform_key",
            "is_active",
        ),
        Index(
            "ux_msg_client_profile__platform_path_token_active",
            "platform_key",
            "path_token",
            unique=True,
            postgresql_where=sa_text(
                "is_active = true AND path_token IS NOT NULL"
            ),
        ),
        Index(
            "ux_msg_client_profile__platform_recipient_user_active",
            "platform_key",
            "recipient_user_id",
            unique=True,
            postgresql_where=sa_text(
                "is_active = true AND recipient_user_id IS NOT NULL"
            ),
        ),
        Index(
            "ux_msg_client_profile__platform_account_number_active",
            "platform_key",
            "account_number",
            unique=True,
            postgresql_where=sa_text(
                "is_active = true AND account_number IS NOT NULL"
            ),
        ),
        Index(
            "ux_msg_client_profile__platform_phone_number_active",
            "platform_key",
            "phone_number_id",
            unique=True,
            postgresql_where=sa_text(
                "is_active = true AND phone_number_id IS NOT NULL"
            ),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"MessagingClientProfile(id={self.id!r})"
