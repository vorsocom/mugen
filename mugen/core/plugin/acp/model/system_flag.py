"""Provides an ORM for system flags."""

__all__ = ["SystemFlag"]

from sqlalchemy import Boolean, CheckConstraint, Index, Text, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class SystemFlag(ModelBase):
    """An ORM for system flags."""

    __tablename__ = "admin_system_flag"

    namespace: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=True,
    )

    is_set: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa_false(),
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_system_flag__namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_system_flag__name_nonempty",
        ),
        UniqueConstraint(
            "namespace",
            "name",
            name="ux_system_flag__namespace_name",
        ),
        Index("ix_system_flag__namespace_name", "namespace", "name"),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SystemFlag(id={self.id!r})"
