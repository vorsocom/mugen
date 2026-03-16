"""Provides an SMTP outbound email gateway."""

__all__ = ["SMTPEmailGateway"]

import asyncio
from email.message import EmailMessage
from email.utils import make_msgid
import mimetypes
import os
import smtplib
from types import SimpleNamespace

from mugen.core.contract.gateway.email import (
    EmailAttachment,
    EmailGatewayError,
    EmailSendRequest,
    EmailSendResult,
    IEmailGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.utility.config_value import parse_optional_positive_finite_float


# pylint: disable=too-few-public-methods
class SMTPEmailGateway(IEmailGateway):
    """An SMTP-based outbound email gateway."""

    _provider = "smtp"
    _operation = "send_email"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._smtp_config = self._resolve_smtp_config()

    async def check_readiness(self) -> None:
        if not isinstance(self._smtp_config, dict):
            raise RuntimeError("SMTP gateway configuration is unavailable.")
        required = ("host", "port", "timeout_seconds")
        missing = [key for key in required if key not in self._smtp_config]
        if missing:
            raise RuntimeError(
                "SMTP gateway configuration is incomplete: "
                f"{', '.join(sorted(missing))}."
            )
        timeout_seconds = float(self._smtp_config["timeout_seconds"])
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._probe_smtp_connectivity),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError("SMTP gateway readiness probe failed.") from exc

    def _probe_smtp_connectivity(self) -> None:
        host = str(self._smtp_config["host"])
        port = int(self._smtp_config["port"])
        timeout_seconds = float(self._smtp_config["timeout_seconds"])
        use_ssl = bool(self._smtp_config["use_ssl"])
        starttls = bool(self._smtp_config["starttls"])
        username = self._smtp_config["username"]
        password = self._smtp_config["password"]

        client_factory = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with client_factory(host=host, port=port, timeout=timeout_seconds) as client:
            if use_ssl:
                client.noop()
            else:
                client.ehlo()
                if starttls:
                    client.starttls()
                    client.ehlo()
                client.noop()
            if isinstance(username, str) and isinstance(password, str):
                client.login(username, password)

    async def send_email(self, request: EmailSendRequest) -> EmailSendResult:
        if not isinstance(request, EmailSendRequest):
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message="request must be an EmailSendRequest instance.",
            )

        try:
            return await asyncio.to_thread(self._send_email_blocking, request)
        except EmailGatewayError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "SMTPEmailGateway.send_email: "
                "Unexpected failure while processing outbound email request."
            )
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message="Unexpected SMTP email gateway failure.",
                cause=exc,
            ) from exc

    def _resolve_smtp_config(self) -> dict[str, object]:
        try:
            smtp_cfg = self._config.smtp
        except AttributeError as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="Missing SMTP configuration section: [smtp].",
                cause=exc,
            ) from exc

        host = self._required_string(getattr(smtp_cfg, "host", None), "smtp.host")

        use_ssl = self._required_bool(
            getattr(smtp_cfg, "use_ssl", False),
            "smtp.use_ssl",
        )
        starttls = self._required_bool(
            getattr(smtp_cfg, "starttls", False),
            "smtp.starttls",
        )
        starttls_required = self._required_bool(
            getattr(smtp_cfg, "starttls_required", False),
            "smtp.starttls_required",
        )
        if starttls_required:
            starttls = True

        if use_ssl and starttls:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="SMTP config cannot enable use_ssl and starttls together.",
            )

        port = getattr(smtp_cfg, "port", None)
        if port is None:
            port = 465 if use_ssl else 587
        try:
            port = int(port)
        except (TypeError, ValueError) as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="smtp.port must be an integer.",
                cause=exc,
            ) from exc

        if port <= 0:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="smtp.port must be greater than zero.",
            )

        timeout_seconds = getattr(smtp_cfg, "timeout_seconds", 30.0)
        try:
            parsed_timeout = parse_optional_positive_finite_float(
                timeout_seconds,
                "smtp.timeout_seconds",
            )
        except RuntimeError as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=str(exc).replace("Invalid configuration: ", ""),
                cause=exc,
            ) from exc
        timeout_seconds = 30.0 if parsed_timeout is None else parsed_timeout

        username = self._optional_string(getattr(smtp_cfg, "username", None))
        password = self._optional_string(getattr(smtp_cfg, "password", None))
        if (username is None) != (password is None):
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="smtp.username and smtp.password must be configured together.",
            )

        default_from = self._optional_string(getattr(smtp_cfg, "default_from", None))

        return {
            "host": host,
            "port": port,
            "timeout_seconds": timeout_seconds,
            "use_ssl": use_ssl,
            "starttls": starttls,
            "starttls_required": starttls_required,
            "username": username,
            "password": password,
            "default_from": default_from,
        }

    def _send_email_blocking(self, request: EmailSendRequest) -> EmailSendResult:
        sender = request.from_address or self._smtp_config["default_from"]
        if sender is None:
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=(
                    "Sender address is required. Provide request.from_address "
                    "or configure smtp.default_from."
                ),
            )

        message = self._build_message(request, sender=sender)
        recipients = self._resolve_all_recipients(request)

        try:
            rejected = self._send_via_smtp(
                message=message,
                sender=sender,
                recipients=recipients,
            )
        except EmailGatewayError:
            raise
        except (smtplib.SMTPException, OSError) as exc:
            self._logging_gateway.warning(
                "SMTPEmailGateway.send_email: SMTP transport operation failed."
            )
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=f"SMTP transport error: {exc}",
                cause=exc,
            ) from exc

        rejected_recipients = [
            recipient for recipient in recipients if recipient in rejected
        ]
        accepted_recipients = [
            recipient for recipient in recipients if recipient not in rejected
        ]

        return EmailSendResult(
            message_id=message.get("Message-ID"),
            accepted_recipients=accepted_recipients,
            rejected_recipients=rejected_recipients,
        )

    def _build_message(self, request: EmailSendRequest, *, sender: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = request.subject
        message["From"] = sender

        if request.to:
            message["To"] = ", ".join(request.to)
        if request.cc:
            message["Cc"] = ", ".join(request.cc)
        if request.reply_to is not None:
            message["Reply-To"] = request.reply_to

        message["Message-ID"] = make_msgid()

        for header_key, header_value in request.headers.items():
            message[header_key] = header_value

        if request.text_body is not None and request.html_body is not None:
            message.set_content(request.text_body)
            message.add_alternative(request.html_body, subtype="html")
        elif request.html_body is not None:
            message.set_content(request.html_body, subtype="html")
        else:
            message.set_content(request.text_body)

        for attachment in request.attachments:
            self._add_attachment(message, attachment)

        return message

    def _resolve_all_recipients(self, request: EmailSendRequest) -> list[str]:
        recipients = request.to + request.cc + request.bcc
        deduped_recipients: list[str] = []
        for recipient in recipients:
            if recipient not in deduped_recipients:
                deduped_recipients.append(recipient)
        return deduped_recipients

    def _send_via_smtp(
        self,
        *,
        message: EmailMessage,
        sender: str,
        recipients: list[str],
    ) -> dict[str, tuple[int, bytes]]:
        smtp_client: smtplib.SMTP
        if self._smtp_config["use_ssl"]:
            smtp_client = smtplib.SMTP_SSL(
                host=self._smtp_config["host"],
                port=self._smtp_config["port"],
                timeout=self._smtp_config["timeout_seconds"],
            )
        else:
            smtp_client = smtplib.SMTP(
                host=self._smtp_config["host"],
                port=self._smtp_config["port"],
                timeout=self._smtp_config["timeout_seconds"],
            )

        with smtp_client as client:
            self._apply_transport_security(client)
            self._apply_login(client)
            rejected = client.send_message(
                message,
                from_addr=sender,
                to_addrs=recipients,
            )

        if not isinstance(rejected, dict):
            return {}

        return rejected

    def _apply_transport_security(self, smtp_client: smtplib.SMTP) -> None:
        if not self._smtp_config["starttls"]:
            return

        try:
            smtp_client.starttls()
        except (smtplib.SMTPException, OSError) as exc:
            if self._smtp_config["starttls_required"]:
                raise EmailGatewayError(
                    provider=self._provider,
                    operation=self._operation,
                    message=f"SMTP STARTTLS failed: {exc}",
                    cause=exc,
                ) from exc

            self._logging_gateway.warning(
                "SMTPEmailGateway.send_email: "
                f"SMTP STARTTLS failed but is optional ({exc})."
            )

    def _apply_login(self, smtp_client: smtplib.SMTP) -> None:
        username = self._smtp_config["username"]
        if username is None:
            return

        try:
            smtp_client.login(
                username,
                self._smtp_config["password"],
            )
        except smtplib.SMTPException as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=f"SMTP authentication failed: {exc}",
                cause=exc,
            ) from exc

    def _add_attachment(
        self,
        message: EmailMessage,
        attachment: EmailAttachment,
    ) -> None:
        filename = attachment.filename
        content_bytes: bytes

        if attachment.path is not None:
            if filename is None:
                filename = os.path.basename(attachment.path)

            try:
                with open(attachment.path, "rb") as file_obj:
                    content_bytes = file_obj.read()
            except OSError as exc:
                raise EmailGatewayError(
                    provider=self._provider,
                    operation=self._operation,
                    message=(
                        "Could not read email attachment from path: "
                        f"{attachment.path}"
                    ),
                    cause=exc,
                ) from exc
        else:
            content_bytes = bytes(attachment.content_bytes)
            if filename is None:
                raise EmailGatewayError(
                    provider=self._provider,
                    operation=self._operation,
                    message=(
                        "Attachment filename is required "
                        "when using content_bytes source."
                    ),
                )

        mime_type = attachment.mime_type
        if mime_type is None:
            guessed_mime_type, _ = mimetypes.guess_type(filename)
            mime_type = guessed_mime_type or "application/octet-stream"

        try:
            mime_main_type, mime_sub_type = mime_type.split("/", maxsplit=1)
            if mime_main_type == "" or mime_sub_type == "":
                raise ValueError("Malformed MIME type.")
        except ValueError as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=f"Invalid attachment mime_type: {mime_type}",
                cause=exc,
            ) from exc

        message.add_attachment(
            content_bytes,
            maintype=mime_main_type,
            subtype=mime_sub_type,
            filename=filename,
        )

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str) or value.strip() == "":
            raise EmailGatewayError(
                provider=SMTPEmailGateway._provider,
                operation="initialization",
                message=f"{field_name} must be a non-empty string.",
            )
        return value.strip()

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise EmailGatewayError(
                provider=SMTPEmailGateway._provider,
                operation="initialization",
                message="SMTP string settings must be strings when provided.",
            )

        stripped = value.strip()
        if stripped == "":
            return None

        return stripped

    @staticmethod
    def _required_bool(value: object, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise EmailGatewayError(
            provider=SMTPEmailGateway._provider,
            operation="initialization",
            message=(
                f"{field_name} must be a boolean value "
                "(true/false, yes/no, on/off, 1/0)."
            ),
        )
