"""Provides a domain entity for the ConnectorType DB model."""

__all__ = ["ConnectorTypeDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class ConnectorTypeDE(BaseDE):
    """A domain entity for the ops_connector ConnectorType DB model."""

    key: str | None = None
    display_name: str | None = None
    adapter_kind: str | None = None
    capabilities_json: dict[str, Any] | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
