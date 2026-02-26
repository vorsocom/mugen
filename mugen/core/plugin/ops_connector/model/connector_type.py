"""Provides an ORM for connector-type registry rows."""

from __future__ import annotations

__all__ = ["ConnectorType"]

from sqlalchemy import Boolean, CheckConstraint, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class ConnectorType(ModelBase):
    """Global connector type registry for runtime adapter definitions."""

    __tablename__ = "ops_connector_type"

    key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    adapter_kind: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
        server_default=sa_text("'http_json'"),
    )

    capabilities_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("'{}'::jsonb"),
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
            "length(btrim(key)) > 0",
            name="ck_ops_connector_type__key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_connector_type__display_name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(adapter_kind)) > 0",
            name="ck_ops_connector_type__adapter_kind_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(capabilities_json) = 'object'",
            name="ck_ops_connector_type__capabilities_json_object",
        ),
        UniqueConstraint(
            "key",
            name="ux_ops_connector_type__key",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ConnectorType(id={self.id!r})"
