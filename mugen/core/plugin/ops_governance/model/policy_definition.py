"""Provides an ORM for governance policy definitions."""

from __future__ import annotations

__all__ = ["PolicyDefinition"]

from datetime import datetime
import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String
from sqlalchemy import UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class PolicyDefinition(ModelBase, TenantScopedMixin):
    """An ORM for generic policy metadata definitions."""

    __tablename__ = "ops_governance_policy_definition"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    policy_type: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    rule_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    evaluation_mode: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'advisory'"),
    )

    engine: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'dsl'"),
    )

    version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_evaluated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    last_decision_log_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    document_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_policy_definition__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_policy_definition__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_policy_definition__description_nonempty_if_set",
        ),
        CheckConstraint(
            "policy_type IS NULL OR length(btrim(policy_type)) > 0",
            name="ck_ops_gov_policy_definition__policy_type_nonempty_if_set",
        ),
        CheckConstraint(
            "rule_ref IS NULL OR length(btrim(rule_ref)) > 0",
            name="ck_ops_gov_policy_definition__rule_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(evaluation_mode)) > 0",
            name="ck_ops_gov_policy_definition__evaluation_mode_nonempty",
        ),
        CheckConstraint(
            "length(btrim(engine)) > 0",
            name="ck_ops_gov_policy_definition__engine_nonempty",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_ops_gov_policy_definition__version_positive",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_policy_definition__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            "version",
            name="ux_ops_gov_policy_definition__tenant_code_version",
        ),
        Index(
            "ux_ops_gov_policy_definition__tenant_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=sa_text("is_active = true"),
        ),
        Index(
            "ix_ops_gov_policy_definition__tenant_type_active",
            "tenant_id",
            "policy_type",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"PolicyDefinition(id={self.id!r})"
