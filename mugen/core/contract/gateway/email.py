"""Provides an abstract base class for outbound email gateways."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def _normalise_email_address_list(
    value: list[str],
    *,
    field_name: str,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of email addresses.")

    normalised: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")

        address = item.strip()
        if address == "":
            raise ValueError(f"{field_name} entries must be non-empty strings.")

        normalised.append(address)

    return normalised


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
class EmailAttachment:
    """An outbound email attachment sourced from a file path or bytes."""

    path: str | None = None
    content_bytes: bytes | None = None
    filename: str | None = None
    mime_type: str | None = None

    def __post_init__(self) -> None:
        path = _normalise_optional_string(self.path, field_name="Attachment path")
        filename = _normalise_optional_string(
            self.filename,
            field_name="Attachment filename",
        )
        mime_type = _normalise_optional_string(
            self.mime_type,
            field_name="Attachment mime_type",
        )

        content_bytes = self.content_bytes
        if content_bytes is not None:
            if not isinstance(content_bytes, (bytes, bytearray, memoryview)):
                raise ValueError("Attachment content_bytes must be bytes.")
            content_bytes = bytes(content_bytes)

        if (path is None and content_bytes is None) or (
            path is not None and content_bytes is not None
        ):
            raise ValueError(
                "Attachment must provide exactly one source: path or content_bytes."
            )

        if content_bytes is not None and filename is None:
            raise ValueError(
                "Attachment filename is required when content_bytes is provided."
            )

        object.__setattr__(self, "path", path)
        object.__setattr__(self, "content_bytes", content_bytes)
        object.__setattr__(self, "filename", filename)
        object.__setattr__(self, "mime_type", mime_type)


@dataclass(frozen=True)
class EmailSendRequest:
    """A normalized outbound email request payload."""

    to: list[str]
    subject: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    text_body: str | None = None
    html_body: str | None = None
    from_address: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[EmailAttachment] = field(default_factory=list)

    def __post_init__(self) -> None:
        to = _normalise_email_address_list(self.to, field_name="to")
        cc = _normalise_email_address_list(self.cc, field_name="cc")
        bcc = _normalise_email_address_list(self.bcc, field_name="bcc")

        if not (to or cc or bcc):
            raise ValueError("At least one recipient is required in to, cc, or bcc.")

        if not isinstance(self.subject, str):
            raise ValueError("subject must be a string.")
        subject = self.subject.strip()
        if subject == "":
            raise ValueError("subject must be a non-empty string.")

        text_body = _normalise_optional_string(self.text_body, field_name="text_body")
        html_body = _normalise_optional_string(self.html_body, field_name="html_body")

        if text_body is None and html_body is None:
            raise ValueError("Either text_body or html_body must be provided.")

        from_address = _normalise_optional_string(
            self.from_address,
            field_name="from_address",
        )
        reply_to = _normalise_optional_string(
            self.reply_to,
            field_name="reply_to",
        )

        if not isinstance(self.headers, dict):
            raise ValueError("headers must be a dictionary.")

        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("headers keys must be non-empty strings.")
            if not isinstance(value, str):
                raise ValueError("headers values must be strings.")
            headers[key.strip()] = value

        if not isinstance(self.attachments, list):
            raise ValueError("attachments must be a list.")

        attachments: list[EmailAttachment] = []
        for attachment in self.attachments:
            if not isinstance(attachment, EmailAttachment):
                raise ValueError("attachments entries must be EmailAttachment instances.")
            attachments.append(attachment)

        object.__setattr__(self, "to", to)
        object.__setattr__(self, "cc", cc)
        object.__setattr__(self, "bcc", bcc)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "text_body", text_body)
        object.__setattr__(self, "html_body", html_body)
        object.__setattr__(self, "from_address", from_address)
        object.__setattr__(self, "reply_to", reply_to)
        object.__setattr__(self, "headers", headers)
        object.__setattr__(self, "attachments", attachments)


@dataclass(frozen=True)
class EmailSendResult:
    """Normalized outbound email send result payload."""

    message_id: str | None
    accepted_recipients: list[str] = field(default_factory=list)
    rejected_recipients: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        message_id = _normalise_optional_string(
            self.message_id,
            field_name="message_id",
        )
        accepted_recipients = _normalise_email_address_list(
            self.accepted_recipients,
            field_name="accepted_recipients",
        )
        rejected_recipients = _normalise_email_address_list(
            self.rejected_recipients,
            field_name="rejected_recipients",
        )

        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "accepted_recipients", accepted_recipients)
        object.__setattr__(self, "rejected_recipients", rejected_recipients)


class EmailGatewayError(RuntimeError):
    """Raised when an email gateway cannot fulfill an outbound operation."""

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


class IEmailGateway(ABC):  # pylint: disable=too-few-public-methods
    """An abstract base class for outbound email gateways."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness for startup fail-fast checks."""

    @abstractmethod
    async def send_email(self, request: EmailSendRequest) -> EmailSendResult:
        """Send an outbound email."""
