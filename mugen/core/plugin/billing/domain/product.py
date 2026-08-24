"""Provides a domain entity for the Product DB model."""

__all__ = ["ProductDE"]

from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class ProductDE(BaseDE, SoftDeleteDEMixin):
    """A domain entity for the billing Product DB model."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    prices: Sequence["PriceDE"] | None = None  # type: ignore
