"""Provides a base for Pydantic data validators."""

from pydantic import NonNegativeInt

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class NoValidationSchema(IValidationBase):
    """No structural validation."""


class RowVersionValidation(IValidationBase):
    """Validate that RowVersion was provided."""

    row_version: NonNegativeInt
