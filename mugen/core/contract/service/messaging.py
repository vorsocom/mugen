"""Provides typed contracts for messaging services."""

from __future__ import annotations

__all__ = ["IMessagingService", "MessagingTurnRequest"]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mugen.core.contract.context import ContextScope
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rpp import IRPPExtension


def _normalize_payload_list(value: object, *, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list[dict].")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field_name} entries must be dict values.")
        normalized.append(dict(item))
    return normalized


def _normalize_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dict.")
    return dict(value)


@dataclass(frozen=True, slots=True)
class MessagingTurnRequest:
    """Typed inbound turn contract for messaging orchestration."""

    scope: ContextScope
    message_type: str
    message: str | dict[str, Any]
    message_id: str | None = None
    trace_id: str | None = None
    message_context: list[dict[str, Any]] = field(default_factory=list)
    attachment_context: list[dict[str, Any]] = field(default_factory=list)
    ingress_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ContextScope):
            raise TypeError("MessagingTurnRequest.scope must be ContextScope.")
        message_type = str(self.message_type or "").strip().lower()
        if message_type == "":
            raise ValueError("MessagingTurnRequest.message_type is required.")
        object.__setattr__(self, "message_type", message_type)
        if not isinstance(self.message, (str, dict)):
            raise TypeError("MessagingTurnRequest.message must be str or dict.")
        object.__setattr__(
            self,
            "message_context",
            _normalize_payload_list(
                self.message_context,
                field_name="MessagingTurnRequest.message_context",
            ),
        )
        object.__setattr__(
            self,
            "attachment_context",
            _normalize_payload_list(
                self.attachment_context,
                field_name="MessagingTurnRequest.attachment_context",
            ),
        )
        object.__setattr__(
            self,
            "ingress_metadata",
            _normalize_mapping(
                self.ingress_metadata,
                field_name="MessagingTurnRequest.ingress_metadata",
            ),
        )


class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    @abstractmethod
    def bind_cp_extension(self, ext: ICPExtension, *, critical: bool = False) -> None:
        """Bind a CP extension to the service runtime."""

    @abstractmethod
    def bind_ct_extension(self, ext: ICTExtension, *, critical: bool = False) -> None:
        """Bind a CT extension to the service runtime."""

    @abstractmethod
    def bind_mh_extension(self, ext: IMHExtension, *, critical: bool = False) -> None:
        """Bind an MH extension to the service runtime."""

    @abstractmethod
    def bind_rpp_extension(self, ext: IRPPExtension, *, critical: bool = False) -> None:
        """Bind an RPP extension to the service runtime."""

    @property
    @abstractmethod
    def cp_extensions(self) -> list[ICPExtension]:
        """Get the list of CP extensions registered with the service."""

    @property
    @abstractmethod
    def ct_extensions(self) -> list[ICTExtension]:
        """Get the list of CT extensions registered with the service."""

    @property
    @abstractmethod
    def mh_extensions(self) -> list[IMHExtension]:
        """Get the list of MH extensions registered with the service."""

    @property
    @abstractmethod
    def rpp_extensions(self) -> list[IRPPExtension]:
        """Get the list of RPP extensions registered with the service."""

    @abstractmethod
    async def handle_message(
        self,
        request: MessagingTurnRequest,
    ) -> list[dict[str, Any]] | None:
        """Handle one typed inbound message turn."""
