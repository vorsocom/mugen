"""Unit tests for mugen.core.gateway.email.smtp.SMTPEmailGateway."""

from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from mugen.core.contract.gateway.email import (
    EmailAttachment,
    EmailGatewayError,
    EmailSendRequest,
)
from mugen.core.gateway.email.smtp import SMTPEmailGateway


def _make_config(
    *,
    host: str = "smtp.example.com",
    port: int = 587,
    timeout_seconds: float = 30.0,
    default_from: str | None = "default@example.com",
    use_ssl: bool = False,
    starttls: bool = False,
    starttls_required: bool = False,
    username: str | None = None,
    password: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        smtp=SimpleNamespace(
            host=host,
            port=port,
            timeout_seconds=timeout_seconds,
            default_from=default_from,
            use_ssl=use_ssl,
            starttls=starttls,
            starttls_required=starttls_required,
            username=username,
            password=password,
        )
    )


def _smtp_client(*, rejected=None) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.send_message.return_value = rejected or {}
    return client


class TestMugenGatewayEmailSMTP(unittest.IsolatedAsyncioTestCase):
    """Covers request serialization and SMTP transport behavior."""

    async def test_send_email_sends_text_only_email(self) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            result = await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Hello",
                    text_body="hello text",
                )
            )

        sent_message = smtp_client.send_message.call_args.args[0]
        self.assertEqual(sent_message["Subject"], "Hello")
        self.assertEqual(sent_message["From"], "default@example.com")
        self.assertEqual(sent_message["To"], "to@example.com")
        self.assertIn("hello text", sent_message.get_body(("plain",)).get_content())

        self.assertEqual(result.accepted_recipients, ["to@example.com"])
        self.assertEqual(result.rejected_recipients, [])
        self.assertIsNotNone(result.message_id)

    async def test_send_email_sends_text_and_html_multipart_email(self) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Multipart",
                    text_body="plain body",
                    html_body="<p>html body</p>",
                )
            )

        sent_message = smtp_client.send_message.call_args.args[0]
        self.assertTrue(sent_message.is_multipart())
        self.assertIn("plain body", sent_message.get_body(("plain",)).get_content())
        self.assertIn("html body", sent_message.get_body(("html",)).get_content())

    async def test_send_email_supports_path_and_memory_attachments(self) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()

        temp_file = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
        try:
            temp_file.write(b"from file")
            temp_file.close()

            with (
                patch(
                    "mugen.core.gateway.email.smtp.smtplib.SMTP",
                    return_value=smtp_client,
                ),
                patch(
                    "mugen.core.gateway.email.smtp.asyncio.to_thread",
                    new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
                ),
            ):
                gateway = SMTPEmailGateway(config, logging_gateway)
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="Attachments",
                        text_body="body",
                        attachments=[
                            EmailAttachment(path=temp_file.name, mime_type="text/plain"),
                            EmailAttachment(
                                content_bytes=b"from memory",
                                filename="memory.bin",
                                mime_type="application/octet-stream",
                            ),
                        ],
                    )
                )

            sent_message = smtp_client.send_message.call_args.args[0]
            attachments = list(sent_message.iter_attachments())
            self.assertEqual(len(attachments), 2)
            self.assertEqual(attachments[0].get_filename(), os.path.basename(temp_file.name))
            self.assertEqual(attachments[1].get_filename(), "memory.bin")
        finally:
            os.unlink(temp_file.name)

    async def test_send_email_applies_default_sender_and_request_override(self) -> None:
        config = _make_config(default_from="default@example.com", starttls=False)
        logging_gateway = Mock()

        first_client = _smtp_client()
        second_client = _smtp_client()

        with (
            patch(
                "mugen.core.gateway.email.smtp.smtplib.SMTP",
                side_effect=[first_client, second_client],
            ),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Default sender",
                    text_body="body",
                )
            )
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Override sender",
                    text_body="body",
                    from_address="override@example.com",
                )
            )

        first_message = first_client.send_message.call_args.args[0]
        second_message = second_client.send_message.call_args.args[0]
        self.assertEqual(first_message["From"], "default@example.com")
        self.assertEqual(second_message["From"], "override@example.com")

    async def test_send_email_handles_tls_modes_and_login_behavior(self) -> None:
        starttls_config = _make_config(
            starttls=True,
            starttls_required=True,
            username="smtp-user",
            password="smtp-pass",
        )
        ssl_config = _make_config(
            use_ssl=True,
            starttls=False,
            username="smtp-user",
            password="smtp-pass",
        )
        logging_gateway = Mock()

        starttls_client = _smtp_client()
        ssl_client = _smtp_client()

        with (
            patch(
                "mugen.core.gateway.email.smtp.smtplib.SMTP",
                return_value=starttls_client,
            ) as smtp_ctor,
            patch(
                "mugen.core.gateway.email.smtp.smtplib.SMTP_SSL",
                return_value=ssl_client,
            ) as smtp_ssl_ctor,
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway_starttls = SMTPEmailGateway(starttls_config, logging_gateway)
            await gateway_starttls.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="StartTLS",
                    text_body="body",
                )
            )

            gateway_ssl = SMTPEmailGateway(ssl_config, logging_gateway)
            await gateway_ssl.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="SSL",
                    text_body="body",
                )
            )

        smtp_ctor.assert_called_once()
        smtp_ssl_ctor.assert_called_once()
        starttls_client.starttls.assert_called_once()
        starttls_client.login.assert_called_once_with("smtp-user", "smtp-pass")
        ssl_client.starttls.assert_not_called()
        ssl_client.login.assert_called_once_with("smtp-user", "smtp-pass")

    async def test_send_email_returns_accepted_and_rejected_recipients(self) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client(
            rejected={"bad@example.com": (550, b"Mailbox unavailable")}
        )

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            result = await gateway.send_email(
                EmailSendRequest(
                    to=["good@example.com", "bad@example.com"],
                    subject="Recipients",
                    text_body="body",
                )
            )

        self.assertEqual(result.accepted_recipients, ["good@example.com"])
        self.assertEqual(result.rejected_recipients, ["bad@example.com"])
        self.assertIsNotNone(result.message_id)

    async def test_send_email_raises_email_gateway_error_on_smtp_exception(self) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()
        smtp_client.send_message.side_effect = smtplib.SMTPException("boom")

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="Failure",
                        text_body="body",
                    )
                )

        self.assertIn("SMTP transport error", str(ctx.exception))
        self.assertIsInstance(ctx.exception.cause, smtplib.SMTPException)

    async def test_send_email_raises_email_gateway_error_on_attachment_path_error(
        self,
    ) -> None:
        config = _make_config(starttls=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="Attachment failure",
                        text_body="body",
                        attachments=[EmailAttachment(path="/no/such/file")],
                    )
                )

        self.assertIn("Could not read email attachment", str(ctx.exception))
        self.assertIsInstance(ctx.exception.cause, OSError)

    async def test_send_email_rejects_invalid_request_type(self) -> None:
        gateway = SMTPEmailGateway(_make_config(), Mock())

        with self.assertRaises(EmailGatewayError) as ctx:
            await gateway.send_email("invalid")  # type: ignore[arg-type]

        self.assertIn("EmailSendRequest", str(ctx.exception))

    async def test_send_email_wraps_unexpected_exception(self) -> None:
        gateway = SMTPEmailGateway(_make_config(), Mock())

        with patch(
            "mugen.core.gateway.email.smtp.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("Unexpected SMTP email gateway failure", str(ctx.exception))

    def test_constructor_validates_required_and_optional_settings(self) -> None:
        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(SimpleNamespace(), Mock())

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(host=""), Mock())

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(use_ssl=True, starttls=True),
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(port="not-a-port"), Mock())  # type: ignore[arg-type]

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(port=0), Mock())

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(timeout_seconds="bad"),  # type: ignore[arg-type]
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(timeout_seconds=0), Mock())

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(username="user", password=None), Mock())

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(_make_config(username=123), Mock())  # type: ignore[arg-type]

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(use_ssl="maybe"),  # type: ignore[arg-type]
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(starttls="definitely"),  # type: ignore[arg-type]
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(starttls_required="sometimes"),  # type: ignore[arg-type]
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SMTPEmailGateway(
                _make_config(use_ssl=1),  # type: ignore[arg-type]
                Mock(),
            )

        parsed_gateway = SMTPEmailGateway(
            _make_config(use_ssl="on", starttls="off", starttls_required="0"),
            Mock(),
        )
        self.assertTrue(parsed_gateway._smtp_config["use_ssl"])
        self.assertFalse(parsed_gateway._smtp_config["starttls"])
        self.assertFalse(parsed_gateway._smtp_config["starttls_required"])

        gateway = SMTPEmailGateway(
            _make_config(default_from="   ", use_ssl=True, port=None),
            Mock(),
        )
        self.assertIsNone(gateway._smtp_config["default_from"])
        self.assertEqual(gateway._smtp_config["port"], 465)

    async def test_send_email_requires_sender_when_no_default_or_override(self) -> None:
        gateway = SMTPEmailGateway(_make_config(default_from=None, starttls=False), Mock())

        with patch(
            "mugen.core.gateway.email.smtp.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
        ):
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("Sender address is required", str(ctx.exception))

    async def test_send_email_builds_html_only_headers_and_deduped_recipients(self) -> None:
        config = _make_config(starttls=False)
        smtp_client = _smtp_client()

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, Mock())
            await gateway.send_email(
                EmailSendRequest(
                    to=[],
                    cc=["dup@example.com"],
                    bcc=["dup@example.com", "bcc@example.com"],
                    subject="subject",
                    html_body="<p>html</p>",
                    reply_to="reply@example.com",
                    headers={"X-Trace": "abc"},
                )
            )

        sent_message = smtp_client.send_message.call_args.args[0]
        recipient_list = smtp_client.send_message.call_args.kwargs["to_addrs"]
        self.assertEqual(sent_message["Cc"], "dup@example.com")
        self.assertEqual(sent_message["Reply-To"], "reply@example.com")
        self.assertEqual(sent_message["X-Trace"], "abc")
        self.assertIn("html", sent_message.get_body(("html",)).get_content())
        self.assertEqual(recipient_list, ["dup@example.com", "bcc@example.com"])

    async def test_send_email_handles_optional_starttls_failure(self) -> None:
        config = _make_config(starttls=True, starttls_required=False)
        logging_gateway = Mock()
        smtp_client = _smtp_client()
        smtp_client.starttls.side_effect = smtplib.SMTPException("tls failed")

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, logging_gateway)
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="subject",
                    text_body="body",
                )
            )

        logging_gateway.warning.assert_called()

    async def test_send_email_raises_when_starttls_required_fails(self) -> None:
        config = _make_config(starttls=True, starttls_required=True)
        smtp_client = _smtp_client()
        smtp_client.starttls.side_effect = smtplib.SMTPException("tls failed")

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, Mock())
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("SMTP STARTTLS failed", str(ctx.exception))

    async def test_send_email_raises_when_login_fails(self) -> None:
        config = _make_config(starttls=False, username="u", password="p")
        smtp_client = _smtp_client()
        smtp_client.login.side_effect = smtplib.SMTPException("bad auth")

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, Mock())
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("SMTP authentication failed", str(ctx.exception))

    async def test_send_email_handles_non_dict_rejection_payload(self) -> None:
        config = _make_config(starttls=False)
        smtp_client = _smtp_client()
        smtp_client.send_message.return_value = [("bad@example.com", 550)]

        with (
            patch("mugen.core.gateway.email.smtp.smtplib.SMTP", return_value=smtp_client),
            patch(
                "mugen.core.gateway.email.smtp.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
            ),
        ):
            gateway = SMTPEmailGateway(config, Mock())
            result = await gateway.send_email(
                EmailSendRequest(
                    to=["good@example.com"],
                    subject="subject",
                    text_body="body",
                )
            )

        self.assertEqual(result.accepted_recipients, ["good@example.com"])
        self.assertEqual(result.rejected_recipients, [])

    async def test_send_email_rethrows_email_gateway_error_from_transport_layer(self) -> None:
        config = _make_config(starttls=False)

        with patch(
            "mugen.core.gateway.email.smtp.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func, *a, **k: func(*a, **k)),
        ):
            gateway = SMTPEmailGateway(config, Mock())
            with patch.object(
                gateway,
                "_send_via_smtp",
                side_effect=EmailGatewayError(
                    provider="smtp",
                    operation="send_email",
                    message="transport",
                ),
            ):
                with self.assertRaises(EmailGatewayError) as ctx:
                    await gateway.send_email(
                        EmailSendRequest(
                            to=["to@example.com"],
                            subject="subject",
                            text_body="body",
                        )
                    )

        self.assertEqual(str(ctx.exception), "transport")

    def test_add_attachment_handles_filename_override_guess_and_mime_errors(self) -> None:
        gateway = SMTPEmailGateway(_make_config(starttls=False), Mock())
        message = EmailMessage()

        temp_file = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
        try:
            temp_file.write(b"payload")
            temp_file.close()

            gateway._add_attachment(  # pylint: disable=protected-access
                message,
                EmailAttachment(path=temp_file.name, filename="custom-name.txt"),
            )
            first_attachment = list(message.iter_attachments())[0]
            self.assertEqual(first_attachment.get_filename(), "custom-name.txt")

            with self.assertRaises(EmailGatewayError):
                gateway._add_attachment(  # pylint: disable=protected-access
                    EmailMessage(),
                    SimpleNamespace(
                        path=None,
                        content_bytes=b"payload",
                        filename=None,
                        mime_type="application/octet-stream",
                    ),
                )

            with self.assertRaises(EmailGatewayError):
                gateway._add_attachment(  # pylint: disable=protected-access
                    EmailMessage(),
                    SimpleNamespace(
                        path=None,
                        content_bytes=b"payload",
                        filename="memory.bin",
                        mime_type="invalid-mime",
                    ),
                )

            with self.assertRaises(EmailGatewayError):
                gateway._add_attachment(  # pylint: disable=protected-access
                    EmailMessage(),
                    SimpleNamespace(
                        path=None,
                        content_bytes=b"payload",
                        filename="memory.bin",
                        mime_type="/plain",
                    ),
                )
        finally:
            os.unlink(temp_file.name)
