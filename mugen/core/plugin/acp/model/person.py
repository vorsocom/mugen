"""Provides an ORM for persons."""

__all__ = ["Person"]

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class Person(ModelBase):
    """An ORM for persons."""

    __tablename__ = "admin_person"

    first_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    last_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    user: Mapped["User"] = relationship(  # type: ignore
        back_populates="person",
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(first_name)) > 0",
            name="ck_person__first_name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(last_name)) > 0",
            name="ck_person__last_name_nonempty",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Person(id={self.id!r})"
