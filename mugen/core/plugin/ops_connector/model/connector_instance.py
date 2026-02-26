"""Provides an ORM for tenant-scoped connector instances."""

from __future__ import annotations

__all__ = ["ConnectorInstance", "ConnectorInstanceStatus"]

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class ConnectorInstanceStatus(str, enum.Enum):
    """Connector instance lifecycle states."""

    ACTIVE = "active"

    DISABLED = "disabled"

    ERROR = "error"


class ConnectorInstance(ModelBase, TenantScopedMixin):
    """Tenant runtime config for connector invocations."""

    __tablename__ = "ops_connector_instance"

    connector_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mugen.ops_connector_type.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    config_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    secret_ref: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            ConnectorInstanceStatus,
            name="ops_connector_instance_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    escalation_policy_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    retry_policy_json: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_connector_instance__display_name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(secret_ref)) > 0",
            name="ck_ops_connector_instance__secret_ref_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(config_json) = 'object'",
            name="ck_ops_connector_instance__config_json_object",
        ),
        CheckConstraint(
            (
                "retry_policy_json IS NULL OR "
                "jsonb_typeof(retry_policy_json) = 'object'"
            ),
            name="ck_ops_connector_instance__retry_policy_json_object_if_set",
        ),
        CheckConstraint(
            (
                "escalation_policy_key IS NULL OR "
                "length(btrim(escalation_policy_key)) > 0"
            ),
            name="ck_ops_connector_instance__escalation_policy_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_connector_instance__tenant_id_id",
        ),
        Index(
            "ix_ops_connector_instance__tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_ops_connector_instance__tenant_type",
            "tenant_id",
            "connector_type_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ConnectorInstance(id={self.id!r})"
