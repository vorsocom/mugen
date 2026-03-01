"""Unit tests for mugen.core.gateway.email.ses.SESEmailGateway."""

from __future__ import annotations

from email.message import EmailMessage
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from botocore.exceptions import ClientError, EndpointConnectionError

from mugen.core.contract.gateway.email import (
    EmailAttachment,
    EmailGatewayError,
    EmailSendRequest,
)
from mugen.core.gateway.email.ses import SESEmailGateway


def _make_config(
    *,
    region: str = "us-east-1",
    access_key_id: str | None = "akid",
    secret_access_key: str | None = "secret",
    session_token: str | None = None,
    endpoint_url: str | None = None,
    default_from: str | None = "default@example.com",
    configuration_set_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        aws=SimpleNamespace(
            ses=SimpleNamespace(
                api=SimpleNamespace(
                    region=region,
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                    session_token=session_token,
                    endpoint_url=endpoint_url,
                ),
                default_from=default_from,
                configuration_set_name=configuration_set_name,
            )
        )
    )


class TestMugenGatewayEmailSES(unittest.IsolatedAsyncioTestCase):
    """Covers request serialization and transport behavior for SES gateway."""

    async def test_check_readiness_validates_configuration_and_client(self) -> None:
        ses_client = Mock()
        ses_client.get_send_quota.return_value = {"Max24HourSend": 1000.0}
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client):
            gateway = SESEmailGateway(_make_config(), Mock())

        await gateway.check_readiness()
        ses_client.get_send_quota.assert_called_once_with()

        gateway._ses_config = None  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "configuration is unavailable"):
            await gateway.check_readiness()

        gateway._ses_config = {}  # pylint: disable=protected-access
        gateway._client = None  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "client is unavailable"):
            await gateway.check_readiness()

    async def test_check_readiness_raises_when_probe_missing_or_failing(self) -> None:
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()):
            gateway = SESEmailGateway(_make_config(), Mock())
        gateway._client = object()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "probe is unavailable"):
            await gateway.check_readiness()

        failing_client = Mock()
        failing_client.get_send_quota.side_effect = RuntimeError("boom")
        with patch(
            "mugen.core.gateway.email.ses.boto3.client",
            return_value=failing_client,
        ):
            failing_gateway = SESEmailGateway(_make_config(), Mock())
        with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
            await failing_gateway.check_readiness()

    def test_constructor_builds_client_with_explicit_credentials(self) -> None:
        config = _make_config(
            region="us-west-2",
            access_key_id="AKIA...",
            secret_access_key="SECRET",
            session_token="SESSION",
            endpoint_url="https://email.us-west-2.amazonaws.com",
            default_from="noreply@example.com",
            configuration_set_name="cfg-set",
        )
        logging_gateway = Mock()
        ses_client = Mock()

        with patch(
            "mugen.core.gateway.email.ses.boto3.client",
            return_value=ses_client,
        ) as client_ctor:
            gateway = SESEmailGateway(config, logging_gateway)

        client_ctor.assert_called_once_with(
            service_name="ses",
            region_name="us-west-2",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="SECRET",
            aws_session_token="SESSION",
            endpoint_url="https://email.us-west-2.amazonaws.com",
        )
        self.assertIs(gateway._client, ses_client)
        self.assertEqual(gateway._ses_config["default_from"], "noreply@example.com")

    def test_constructor_builds_client_without_static_credentials(self) -> None:
        config = _make_config(
            access_key_id=None,
            secret_access_key=None,
            session_token=None,
            endpoint_url=None,
            configuration_set_name=None,
        )

        with patch("mugen.core.gateway.email.ses.boto3.client") as client_ctor:
            SESEmailGateway(config, Mock())

        client_ctor.assert_called_once_with(
            service_name="ses",
            region_name="us-east-1",
        )

    def test_constructor_normalizes_blank_optional_strings(self) -> None:
        config = _make_config(
            endpoint_url="   ",
            default_from="   ",
            configuration_set_name="   ",
        )

        with patch("mugen.core.gateway.email.ses.boto3.client") as client_ctor:
            gateway = SESEmailGateway(config, Mock())

        client_ctor.assert_called_once_with(
            service_name="ses",
            region_name="us-east-1",
            aws_access_key_id="akid",
            aws_secret_access_key="secret",
        )
        self.assertIsNone(gateway._ses_config["endpoint_url"])
        self.assertIsNone(gateway._ses_config["default_from"])
        self.assertIsNone(gateway._ses_config["configuration_set_name"])

    def test_constructor_validates_configuration(self) -> None:
        with self.assertRaises(EmailGatewayError):
            SESEmailGateway(SimpleNamespace(), Mock())

        with self.assertRaises(EmailGatewayError):
            SESEmailGateway(_make_config(region=""), Mock())

        with self.assertRaises(EmailGatewayError):
            SESEmailGateway(
                _make_config(access_key_id="AKIA", secret_access_key=None),
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SESEmailGateway(
                _make_config(
                    access_key_id=None,
                    secret_access_key=None,
                    session_token="SESSION",
                ),
                Mock(),
            )

        with self.assertRaises(EmailGatewayError):
            SESEmailGateway(
                _make_config(endpoint_url=123),  # type: ignore[arg-type]
                Mock(),
            )

    def test_constructor_wraps_client_initialization_errors(self) -> None:
        with patch(
            "mugen.core.gateway.email.ses.boto3.client",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(EmailGatewayError) as ctx:
                SESEmailGateway(_make_config(), Mock())

        self.assertIn("Could not initialize Amazon SES client", str(ctx.exception))

    async def test_send_email_sends_raw_message_with_defaults(self) -> None:
        config = _make_config(configuration_set_name="cfg-set")
        logging_gateway = Mock()
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": "ses-123"}

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(config, logging_gateway)
            result = await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    cc=["shared@example.com"],
                    bcc=["shared@example.com", "bcc@example.com"],
                    subject="Hello",
                    text_body="hello text",
                )
            )

        kwargs = ses_client.send_raw_email.call_args.kwargs
        self.assertEqual(kwargs["Source"], "default@example.com")
        self.assertEqual(
            kwargs["Destinations"],
            ["to@example.com", "shared@example.com", "bcc@example.com"],
        )
        self.assertEqual(kwargs["ConfigurationSetName"], "cfg-set")
        self.assertIsInstance(kwargs["RawMessage"]["Data"], bytes)
        self.assertIn(b"Subject: Hello", kwargs["RawMessage"]["Data"])

        self.assertEqual(result.message_id, "ses-123")
        self.assertEqual(
            result.accepted_recipients,
            ["to@example.com", "shared@example.com", "bcc@example.com"],
        )
        self.assertEqual(result.rejected_recipients, [])

    async def test_send_email_uses_request_from_override_and_no_configuration_set(
        self,
    ) -> None:
        config = _make_config(
            default_from="default@example.com",
            configuration_set_name=None,
        )
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": "ses-456"}

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(config, Mock())
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Override",
                    text_body="body",
                    from_address="override@example.com",
                )
            )

        kwargs = ses_client.send_raw_email.call_args.kwargs
        self.assertEqual(kwargs["Source"], "override@example.com")
        self.assertNotIn("ConfigurationSetName", kwargs)

    async def test_send_email_supports_html_body_and_attachments(self) -> None:
        temp_file = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
        try:
            temp_file.write(b"from file")
            temp_file.close()

            ses_client = Mock()
            ses_client.send_raw_email.return_value = {}

            with (
                patch(
                    "mugen.core.gateway.email.ses.boto3.client",
                    return_value=ses_client,
                ),
                patch(
                    "mugen.core.gateway.email.ses.asyncio.to_thread",
                    new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
                ),
            ):
                gateway = SESEmailGateway(_make_config(), Mock())
                result = await gateway.send_email(
                    EmailSendRequest(
                        to=[],
                        cc=["cc@example.com"],
                        subject="HTML",
                        html_body="<p>html body</p>",
                        reply_to="reply@example.com",
                        headers={"X-Trace": "abc"},
                        attachments=[
                            EmailAttachment(path=temp_file.name),
                            EmailAttachment(
                                content_bytes=b"from bytes",
                                filename="payload.bin",
                            ),
                        ],
                    )
                )

            payload = ses_client.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
            self.assertIn(b"Content-Type: multipart/mixed", payload)
            self.assertIn(b"X-Trace: abc", payload)
            self.assertIn(b"Reply-To: reply@example.com", payload)
            self.assertIn(b"payload.bin", payload)
            self.assertIn(os.path.basename(temp_file.name).encode("utf-8"), payload)

            self.assertIsNone(result.message_id)
            self.assertEqual(result.accepted_recipients, ["cc@example.com"])
        finally:
            os.unlink(temp_file.name)

    async def test_send_email_supports_text_and_html_multipart(self) -> None:
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": "ses-multipart"}

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(_make_config(), Mock())
            await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="Multipart",
                    text_body="plain body",
                    html_body="<p>html body</p>",
                )
            )

        payload = ses_client.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
        self.assertIn(b"multipart/alternative", payload)
        self.assertIn(b"plain body", payload)
        self.assertIn(b"html body", payload)

    async def test_send_email_rejects_invalid_request_type(self) -> None:
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()):
            gateway = SESEmailGateway(_make_config(), Mock())

        with self.assertRaises(EmailGatewayError) as ctx:
            await gateway.send_email("invalid")  # type: ignore[arg-type]

        self.assertIn("EmailSendRequest", str(ctx.exception))

    async def test_send_email_wraps_unexpected_async_failures(self) -> None:
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()):
            gateway = SESEmailGateway(_make_config(), Mock())

        with patch(
            "mugen.core.gateway.email.ses.asyncio.to_thread",
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

        self.assertIn("Unexpected Amazon SES email gateway failure", str(ctx.exception))

    async def test_send_email_requires_sender(self) -> None:
        config = _make_config(default_from=None)

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(config, Mock())
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("Sender address is required", str(ctx.exception))

    async def test_send_email_wraps_client_error(self) -> None:
        error = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "Rejected"}},
            "SendRawEmail",
        )
        logging_gateway = Mock()
        ses_client = Mock()
        ses_client.send_raw_email.side_effect = error

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(_make_config(), logging_gateway)
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("Amazon SES transport error", str(ctx.exception))
        self.assertIs(ctx.exception.cause, error)
        logging_gateway.warning.assert_called_once()

    async def test_send_email_wraps_botocore_errors(self) -> None:
        error = EndpointConnectionError(endpoint_url="https://email.us-east-1.amazonaws.com")
        ses_client = Mock()
        ses_client.send_raw_email.side_effect = error

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(_make_config(), Mock())
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIn("Amazon SES transport error", str(ctx.exception))
        self.assertIs(ctx.exception.cause, error)

    async def test_send_email_rethrows_email_gateway_error_from_client(self) -> None:
        ses_client = Mock()
        ses_client.send_raw_email.side_effect = EmailGatewayError(
            provider="ses",
            operation="send_email",
            message="custom",
        )

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(_make_config(), Mock())
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertEqual(str(ctx.exception), "custom")

    async def test_send_email_normalizes_non_string_message_id(self) -> None:
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": 12345}

        with (
            patch("mugen.core.gateway.email.ses.boto3.client", return_value=ses_client),
            patch(
                "mugen.core.gateway.email.ses.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k)),
            ),
        ):
            gateway = SESEmailGateway(_make_config(), Mock())
            result = await gateway.send_email(
                EmailSendRequest(
                    to=["to@example.com"],
                    subject="subject",
                    text_body="body",
                )
            )

        self.assertEqual(result.message_id, "12345")

    async def test_send_email_rethrows_email_gateway_error_from_async_to_thread(
        self,
    ) -> None:
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()):
            gateway = SESEmailGateway(_make_config(), Mock())

        expected = EmailGatewayError(
            provider="ses",
            operation="send_email",
            message="async-pass-through",
        )

        with patch(
            "mugen.core.gateway.email.ses.asyncio.to_thread",
            new=AsyncMock(side_effect=expected),
        ):
            with self.assertRaises(EmailGatewayError) as ctx:
                await gateway.send_email(
                    EmailSendRequest(
                        to=["to@example.com"],
                        subject="subject",
                        text_body="body",
                    )
                )

        self.assertIs(ctx.exception, expected)

    def test_add_attachment_path_and_validation_branches(self) -> None:
        with patch("mugen.core.gateway.email.ses.boto3.client", return_value=Mock()):
            gateway = SESEmailGateway(_make_config(), Mock())

        temp_file = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
        try:
            temp_file.write(b"payload")
            temp_file.close()

            message = EmailMessage()
            gateway._add_attachment(  # pylint: disable=protected-access
                message,
                EmailAttachment(path=temp_file.name, filename="custom.txt"),
            )
            first_attachment = list(message.iter_attachments())[0]
            self.assertEqual(first_attachment.get_filename(), "custom.txt")

            with self.assertRaises(EmailGatewayError):
                gateway._add_attachment(  # pylint: disable=protected-access
                    EmailMessage(),
                    EmailAttachment(path="/no/such/file"),
                )

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
                        filename="file.bin",
                        mime_type="invalid",
                    ),
                )

            with self.assertRaises(EmailGatewayError):
                gateway._add_attachment(  # pylint: disable=protected-access
                    EmailMessage(),
                    SimpleNamespace(
                        path=None,
                        content_bytes=b"payload",
                        filename="file.bin",
                        mime_type="/plain",
                    ),
                )
        finally:
            os.unlink(temp_file.name)
