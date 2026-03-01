"""Provides an Amazon SES outbound email gateway."""

__all__ = ["SESEmailGateway"]

import asyncio
from email.message import EmailMessage
from email.utils import make_msgid
import mimetypes
import os
from types import SimpleNamespace
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from mugen.core.contract.gateway.email import (
    EmailAttachment,
    EmailGatewayError,
    EmailSendRequest,
    EmailSendResult,
    IEmailGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class SESEmailGateway(IEmailGateway):
    """An Amazon SES gateway for outbound email sending."""

    _provider = "ses"
    _operation = "send_email"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._ses_config = self._resolve_ses_config()
        self._client = self._build_ses_client()

    async def check_readiness(self) -> None:
        if not isinstance(self._ses_config, dict):
            raise RuntimeError("Amazon SES gateway configuration is unavailable.")
        if self._client is None:
            raise RuntimeError("Amazon SES gateway client is unavailable.")

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
                "SESEmailGateway.send_email: "
                "Unexpected failure while processing outbound email request."
            )
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message="Unexpected Amazon SES email gateway failure.",
                cause=exc,
            ) from exc

    def _resolve_ses_config(self) -> dict[str, object]:
        try:
            ses_cfg = self._config.aws.ses
            api_cfg = ses_cfg.api
        except AttributeError as exc:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message="Missing Amazon SES configuration section: [aws.ses].",
                cause=exc,
            ) from exc

        region = self._required_string(
            getattr(api_cfg, "region", None),
            "aws.ses.api.region",
        )
        access_key_id = self._optional_string(
            getattr(api_cfg, "access_key_id", None),
            "aws.ses.api.access_key_id",
        )
        secret_access_key = self._optional_string(
            getattr(api_cfg, "secret_access_key", None),
            "aws.ses.api.secret_access_key",
        )
        session_token = self._optional_string(
            getattr(api_cfg, "session_token", None),
            "aws.ses.api.session_token",
        )
        endpoint_url = self._optional_string(
            getattr(api_cfg, "endpoint_url", None),
            "aws.ses.api.endpoint_url",
        )

        if (access_key_id is None) != (secret_access_key is None):
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "aws.ses.api.access_key_id and "
                    "aws.ses.api.secret_access_key must be configured together."
                ),
            )

        if session_token is not None and access_key_id is None:
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "aws.ses.api.session_token requires static AWS credentials "
                    "(access_key_id and secret_access_key)."
                ),
            )

        default_from = self._optional_string(
            getattr(ses_cfg, "default_from", None),
            "aws.ses.default_from",
        )
        configuration_set_name = self._optional_string(
            getattr(ses_cfg, "configuration_set_name", None),
            "aws.ses.configuration_set_name",
        )

        return {
            "region": region,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "session_token": session_token,
            "endpoint_url": endpoint_url,
            "default_from": default_from,
            "configuration_set_name": configuration_set_name,
        }

    def _build_ses_client(self):
        kwargs: dict[str, Any] = {
            "service_name": "ses",
            "region_name": self._ses_config["region"],
        }

        access_key_id = self._ses_config["access_key_id"]
        if access_key_id is not None:
            kwargs["aws_access_key_id"] = access_key_id
            kwargs["aws_secret_access_key"] = self._ses_config["secret_access_key"]

        session_token = self._ses_config["session_token"]
        if session_token is not None:
            kwargs["aws_session_token"] = session_token

        endpoint_url = self._ses_config["endpoint_url"]
        if endpoint_url is not None:
            kwargs["endpoint_url"] = endpoint_url

        try:
            return boto3.client(**kwargs)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=f"Could not initialize Amazon SES client: {exc}",
                cause=exc,
            ) from exc

    def _send_email_blocking(self, request: EmailSendRequest) -> EmailSendResult:
        sender = request.from_address or self._ses_config["default_from"]
        if sender is None:
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=(
                    "Sender address is required. Provide request.from_address "
                    "or configure aws.ses.default_from."
                ),
            )

        message = self._build_message(request, sender=sender)
        recipients = self._resolve_all_recipients(request)

        request_args: dict[str, Any] = {
            "Source": sender,
            "Destinations": recipients,
            "RawMessage": {
                "Data": message.as_bytes(),
            },
        }

        configuration_set_name = self._ses_config["configuration_set_name"]
        if configuration_set_name is not None:
            request_args["ConfigurationSetName"] = configuration_set_name

        try:
            response = self._client.send_raw_email(**request_args)
        except EmailGatewayError:
            raise
        except (ClientError, BotoCoreError, OSError) as exc:
            self._logging_gateway.warning(
                "SESEmailGateway.send_email: Amazon SES transport operation failed."
            )
            raise EmailGatewayError(
                provider=self._provider,
                operation=self._operation,
                message=f"Amazon SES transport error: {exc}",
                cause=exc,
            ) from exc

        message_id = response.get("MessageId")
        if message_id is not None and not isinstance(message_id, str):
            message_id = str(message_id)

        return EmailSendResult(
            message_id=message_id,
            accepted_recipients=recipients,
            rejected_recipients=[],
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

    def _add_attachment(
        self,
        message: EmailMessage,
        attachment: EmailAttachment,
    ) -> None:
        filename = attachment.filename

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

    def _required_string(self, value: object, field_name: str) -> str:
        if not isinstance(value, str) or value.strip() == "":
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=f"{field_name} must be a non-empty string.",
            )

        return value.strip()

    def _optional_string(self, value: object, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise EmailGatewayError(
                provider=self._provider,
                operation="initialization",
                message=f"{field_name} must be a string when provided.",
            )

        stripped = value.strip()
        if stripped == "":
            return None

        return stripped
