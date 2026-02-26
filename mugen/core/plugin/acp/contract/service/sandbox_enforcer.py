"""Contract for ACP runtime capability sandbox enforcement."""

__all__ = [
    "CapabilityDeniedError",
    "ISandboxEnforcer",
]

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilityDeniedError(PermissionError):
    """Raised when a declared capability is not granted in enforce mode."""

    tenant_id: uuid.UUID | None
    plugin_key: str
    capability: str
    context: Mapping[str, Any]


class ISandboxEnforcer(ABC):
    """Capability sandbox contract used by ACP action dispatch."""

    @abstractmethod
    async def require(
        self,
        tenant_id: uuid.UUID | None,
        plugin_key: str,
        capability: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Require a capability grant for plugin action execution."""
