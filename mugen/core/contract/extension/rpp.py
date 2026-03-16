"""Provides an abstract base class for RPP extensions."""

__all__ = ["IRPPExtension"]

from abc import abstractmethod

from mugen.core.contract.context import ContextScope

from . import IExtensionBase


class IRPPExtension(IExtensionBase):  # pylint: disable=too-few-public-methods
    """An ABC for RPP extensions."""

    @abstractmethod
    async def preprocess_response(
        self,
        room_id: str,
        user_id: str,
        assistant_response: str,
        *,
        scope: ContextScope,
    ) -> str:
        """Preprocess the assistant response."""
