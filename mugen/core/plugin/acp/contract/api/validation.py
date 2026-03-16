"""Provides a base for Pydantic data validators."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, NonNegativeInt
from pydantic.alias_generators import to_pascal


class IValidationBase(BaseModel):
    """A base for Pydantic data validators.."""

    model_config = ConfigDict(
        alias_generator=to_pascal,
        populate_by_name=True,
        extra="ignore",
    )
    """No structural validation."""


@dataclass
class IRowVersionValidation:
    """Validate that RowVersion was provided."""

    row_version: NonNegativeInt
