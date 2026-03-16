"""Provides an ORM for immutable connector invocation call logs."""

from __future__ import annotations

__all__ = ["ConnectorCallLog", "ConnectorCallLogStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class ConnectorCallLogStatus(str, enum.Enum):
    """Connector call-log lifecycle states."""

    OK = "ok"

    RETRYING = "retrying"

    FAILED = "failed"


class ConnectorCallLog(ModelBase, TenantScopedMixin):
    """Tenant-scoped append-only ledger for connector calls and outcomes."""

    __tablename__ = "ops_connector_call_log"

    trace_id: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    connector_instance_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    capability_name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
    )

    client_action_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    request_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
    )

    request_hash: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    response_json: Mapped[dict | list | str | int | float | bool | None] = (
        mapped_column(
            JSONB,
            nullable=True,
        )
    )

    response_hash: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            ConnectorCallLogStatus,
            name="ops_connector_call_log_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'failed'"),
    )

    http_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    duration_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    error_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    escalation_json: Mapped[dict | list | str | int | float | bool | None] = (
        mapped_column(
            JSONB,
            nullable=True,
        )
    )

    invoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    invoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=sa_text("now()"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connector_instance_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_connector_instance.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_connector_instance.id",
            ],
            ondelete="RESTRICT",
            name="fkx_ops_connector_call_log__tenant_instance",
        ),
        CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_ops_connector_call_log__trace_id_nonempty",
        ),
        CheckConstraint(
            "length(btrim(capability_name)) > 0",
            name="ck_ops_connector_call_log__capability_name_nonempty",
        ),
        CheckConstraint(
            ("client_action_key IS NULL OR " "length(btrim(client_action_key)) > 0"),
            name="ck_ops_connector_call_log__client_action_key_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(request_hash)) > 0",
            name="ck_ops_connector_call_log__request_hash_nonempty",
        ),
        CheckConstraint(
            ("response_hash IS NULL OR " "length(btrim(response_hash)) > 0"),
            name="ck_ops_connector_call_log__response_hash_nonempty_if_set",
        ),
        CheckConstraint(
            "attempt_count >= 1",
            name="ck_ops_connector_call_log__attempt_count_positive",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ops_connector_call_log__duration_ms_nonnegative_if_set",
        ),
        CheckConstraint(
            (
                "http_status_code IS NULL OR "
                "(http_status_code >= 100 AND http_status_code <= 599)"
            ),
            name="ck_ops_connector_call_log__http_status_code_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_connector_call_log__tenant_id_id",
        ),
        Index(
            "ix_ops_connector_call_log__tenant_trace",
            "tenant_id",
            "trace_id",
        ),
        Index(
            "ix_ops_connector_call_log__tenant_instance_created",
            "tenant_id",
            "connector_instance_id",
            "created_at",
        ),
        Index(
            "ix_ops_connector_call_log__tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"ConnectorCallLog(id={self.id!r})"
