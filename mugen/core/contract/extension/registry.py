"""Extension registration boundary contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.extension import IExtensionBase


class IExtensionRegistry(ABC):
    """Composition-layer extension registrar."""

    @abstractmethod
    async def register(
        self,
        *,
        app: Any,
        extension_type: str,
        extension: IExtensionBase,
        token: str,
        critical: bool,
    ) -> bool:
        """Register an instantiated extension with runtime services."""

