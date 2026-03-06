"""Provides an abstract base class for outbound SMS gateways."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


def _normalise_required_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    stripped = value.strip()
    if stripped == "":
        raise ValueError(f"{field_name} must be a non-empty string.")

    return stripped


def _normalise_optional_string(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when provided.")

    stripped = value.strip()
    if stripped == "":
        return None

    return stripped


@dataclass(frozen=True)
class SMSSendRequest:
    """A normalized outbound SMS request payload."""

    to: str
    body: str
    from_number: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "to",
            _normalise_required_string(self.to, field_name="to"),
        )
        object.__setattr__(
            self,
            "body",
            _normalise_required_string(self.body, field_name="body"),
        )
        object.__setattr__(
            self,
            "from_number",
            _normalise_optional_string(
                self.from_number,
                field_name="from_number",
            ),
        )


@dataclass(frozen=True)
class SMSSendResult:
    """Normalized outbound SMS send result payload."""

    message_id: str | None
    recipient: str
    provider_status: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "message_id",
            _normalise_optional_string(
                self.message_id,
                field_name="message_id",
            ),
        )
        object.__setattr__(
            self,
            "recipient",
            _normalise_required_string(
                self.recipient,
                field_name="recipient",
            ),
        )
        object.__setattr__(
            self,
            "provider_status",
            _normalise_optional_string(
                self.provider_status,
                field_name="provider_status",
            ),
        )


class SMSGatewayError(RuntimeError):
    """Raised when an SMS gateway cannot fulfill an outbound operation."""

    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.cause = cause


class ISMSGateway(ABC):  # pylint: disable=too-few-public-methods
    """An abstract base class for outbound SMS gateways."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness for startup fail-fast checks."""

    @abstractmethod
    async def send_sms(self, request: SMSSendRequest) -> SMSSendResult:
        """Send an outbound SMS message."""
