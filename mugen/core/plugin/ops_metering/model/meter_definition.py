"""Provides the deprecated tenant meter compatibility view mapping."""

from __future__ import annotations

__all__ = ["MeterDefinition"]

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class MeterDefinition(ModelBase, TenantScopedMixin):
    """A read-only tenant projection of canonical billing meters."""

    __tablename__ = "ops_metering_meter_definition_compat"

    code: Mapped[str] = mapped_column(CITEXT(64), nullable=False)
    unit: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    aggregation_mode: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    successor_entity_set: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = ({"schema": CORE_SCHEMA_TOKEN},)

    def __repr__(self) -> str:
        return f"MeterDefinition(id={self.id!r})"
