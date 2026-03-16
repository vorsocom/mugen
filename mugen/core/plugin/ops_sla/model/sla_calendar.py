"""Provides an ORM for SLA calendars."""

__all__ = ["SlaCalendar"]

from datetime import time

from sqlalchemy import Boolean, CheckConstraint, Index, Time, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class SlaCalendar(ModelBase, TenantScopedMixin):
    """An ORM for SLA calendar definitions."""

    __tablename__ = "ops_sla_calendar"

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

    timezone: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("UTC"),
        index=True,
    )

    business_start_time: Mapped[time] = mapped_column(
        Time(timezone=False),
        nullable=False,
        server_default=sa_text("09:00:00"),
    )

    business_end_time: Mapped[time] = mapped_column(
        Time(timezone=False),
        nullable=False,
        server_default=sa_text("17:00:00"),
    )

    business_days: Mapped[list[int] | None] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa_text("[1,2,3,4,5]::jsonb"),
    )

    holiday_refs: Mapped[list[str] | None] = mapped_column(
        JSONB,
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
            name="ck_ops_sla_calendar__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_calendar__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(timezone)) > 0",
            name="ck_ops_sla_calendar__timezone_nonempty",
        ),
        CheckConstraint(
            "business_start_time < business_end_time",
            name="ck_ops_sla_calendar__business_time_bounds",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_calendar__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_sla_calendar__tenant_code",
        ),
        Index(
            "ix_ops_sla_calendar__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaCalendar(id={self.id!r})"
