"""Provides an ORM for conversation-level orchestration state."""

__all__ = ["ConversationState"]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class ConversationState(ModelBase, TenantScopedMixin):
    """An ORM for multi-channel intake/routing/throttle state."""

    __tablename__ = "channel_orchestration_conversation_state"

    channel_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_channel_profile.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.channel_orchestration_orchestration_policy.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    sender_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    external_conversation_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'open'"),
        index=True,
    )

    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    assigned_queue_name: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    assigned_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    assigned_service_key: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    last_intake_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.channel_orchestration_intake_rule.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    last_intake_result: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    escalation_level: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    is_escalated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    is_throttled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    throttled_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    window_message_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    fallback_mode: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    fallback_target: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    fallback_reason: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    is_fallback_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(sender_key)) > 0",
            name="ck_chorch_state__sender_nonempty",
        ),
        CheckConstraint(
            (
                "external_conversation_ref IS NULL OR "
                "length(btrim(external_conversation_ref)) > 0"
            ),
            name="ck_chorch_state__ext_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_chorch_state__status_nonempty",
        ),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_chorch_state__service_route_nonempty_if_set",
        ),
        CheckConstraint(
            "route_key IS NULL OR length(btrim(route_key)) > 0",
            name="ck_chorch_state__route_nonempty_if_set",
        ),
        CheckConstraint(
            "assigned_queue_name IS NULL OR length(btrim(assigned_queue_name)) > 0",
            name="ck_chorch_state__queue_nonempty_if_set",
        ),
        CheckConstraint(
            "assigned_service_key IS NULL OR length(btrim(assigned_service_key)) > 0",
            name="ck_chorch_state__svc_key_nonempty_if_set",
        ),
        CheckConstraint(
            "last_intake_result IS NULL OR length(btrim(last_intake_result)) > 0",
            name="ck_chorch_state__intake_result_nonempty_if_set",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="ck_chorch_state__escalation_level_nonnegative",
        ),
        CheckConstraint(
            "window_message_count >= 0",
            name="ck_chorch_state__window_count_nonnegative",
        ),
        CheckConstraint(
            "fallback_mode IS NULL OR length(btrim(fallback_mode)) > 0",
            name="ck_chorch_state__fallback_mode_nonempty_if_set",
        ),
        CheckConstraint(
            "fallback_target IS NULL OR length(btrim(fallback_target)) > 0",
            name="ck_chorch_state__fallback_target_nonempty_if_set",
        ),
        CheckConstraint(
            "fallback_reason IS NULL OR length(btrim(fallback_reason)) > 0",
            name="ck_chorch_state__fallback_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_state__tenant_id_id",
        ),
        Index(
            "ix_chorch_state__tenant_sender_status",
            "tenant_id",
            "sender_key",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ConversationState(id={self.id!r})"
