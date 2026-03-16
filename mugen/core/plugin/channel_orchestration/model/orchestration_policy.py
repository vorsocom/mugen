"""Provides an ORM for orchestration policies."""

__all__ = ["OrchestrationPolicy"]

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class OrchestrationPolicy(ModelBase, TenantScopedMixin):
    """An ORM for shared orchestration policy defaults."""

    __tablename__ = "channel_orchestration_orchestration_policy"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    hours_mode: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("always_on"),
        index=True,
    )

    escalation_mode: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("manual"),
        index=True,
    )

    fallback_policy: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("default_route"),
        index=True,
    )

    fallback_target: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    escalation_target: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    escalation_after_seconds: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_chorch_policy__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_chorch_policy__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(hours_mode)) > 0",
            name="ck_chorch_policy__hours_mode_nonempty",
        ),
        CheckConstraint(
            "length(btrim(escalation_mode)) > 0",
            name="ck_chorch_policy__escalation_mode_nonempty",
        ),
        CheckConstraint(
            "length(btrim(fallback_policy)) > 0",
            name="ck_chorch_policy__fallback_policy_nonempty",
        ),
        CheckConstraint(
            "fallback_target IS NULL OR length(btrim(fallback_target)) > 0",
            name="ck_chorch_policy__fallback_target_nonempty_if_set",
        ),
        CheckConstraint(
            "escalation_target IS NULL OR length(btrim(escalation_target)) > 0",
            name="ck_chorch_policy__escalation_target_nonempty_if_set",
        ),
        CheckConstraint(
            "escalation_after_seconds IS NULL OR escalation_after_seconds >= 0",
            name="ck_chorch_policy__escalation_after_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_chorch_policy__tenant_code",
        ),
        Index(
            "ix_chorch_policy__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"OrchestrationPolicy(id={self.id!r})"
