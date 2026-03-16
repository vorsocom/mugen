"""Unit tests for mugen.core.contract.gateway.email."""

import unittest

from mugen.core.contract.gateway.email import (
    EmailAttachment,
    EmailGatewayError,
    EmailSendRequest,
    EmailSendResult,
)


class TestMugenContractGatewayEmail(unittest.TestCase):
    """Covers email contract validation and normalization behavior."""

    def test_send_request_requires_at_least_one_recipient(self) -> None:
        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=[],
                cc=[],
                bcc=[],
                subject="subject",
                text_body="hello",
            )

    def test_send_request_requires_at_least_one_body_variant(self) -> None:
        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["user@example.com"],
                subject="subject",
                text_body=None,
                html_body=None,
            )

    def test_attachment_requires_exactly_one_source(self) -> None:
        with self.assertRaises(ValueError):
            EmailAttachment()

        with self.assertRaises(ValueError):
            EmailAttachment(path="/tmp/file.txt", content_bytes=b"hello")

    def test_attachment_requires_filename_for_byte_content(self) -> None:
        with self.assertRaises(ValueError):
            EmailAttachment(content_bytes=b"abc")

    def test_attachment_rejects_non_bytes_content(self) -> None:
        with self.assertRaises(ValueError):
            EmailAttachment(
                content_bytes="abc",  # type: ignore[arg-type]
                filename="payload.bin",
            )

    def test_send_request_validates_recipient_list_shape(self) -> None:
        with self.assertRaises(ValueError):
            EmailSendRequest(
                to="to@example.com",  # type: ignore[arg-type]
                subject="subject",
                text_body="hello",
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=[1],  # type: ignore[list-item]
                subject="subject",
                text_body="hello",
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["   "],
                subject="subject",
                text_body="hello",
            )

    def test_send_request_normalizes_optional_fields_and_defaults(self) -> None:
        request = EmailSendRequest(
            to=["  to@example.com  "],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            subject="  Subject line  ",
            text_body="  Plain body  ",
            from_address="  sender@example.com  ",
            reply_to="  reply@example.com  ",
            headers={" X-Trace ": "trace-1"},
        )

        self.assertEqual(request.to, ["to@example.com"])
        self.assertEqual(request.cc, ["cc@example.com"])
        self.assertEqual(request.bcc, ["bcc@example.com"])
        self.assertEqual(request.subject, "Subject line")
        self.assertEqual(request.text_body, "Plain body")
        self.assertIsNone(request.html_body)
        self.assertEqual(request.from_address, "sender@example.com")
        self.assertEqual(request.reply_to, "reply@example.com")
        self.assertEqual(request.headers, {"X-Trace": "trace-1"})
        self.assertEqual(request.attachments, [])

    def test_send_request_normalizes_blank_optional_strings(self) -> None:
        request = EmailSendRequest(
            to=["to@example.com"],
            subject="subject",
            text_body="hello",
            from_address="   ",
            reply_to="   ",
        )

        self.assertIsNone(request.from_address)
        self.assertIsNone(request.reply_to)

    def test_send_request_validates_subject_headers_and_attachments(self) -> None:
        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject=1,  # type: ignore[arg-type]
                text_body="hello",
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="   ",
                text_body="hello",
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                from_address=1,  # type: ignore[arg-type]
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                headers=[],  # type: ignore[arg-type]
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                headers={"": "x"},
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                headers={"X-Test": 1},  # type: ignore[dict-item]
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                attachments=(),  # type: ignore[arg-type]
            )

        with self.assertRaises(ValueError):
            EmailSendRequest(
                to=["to@example.com"],
                subject="subject",
                text_body="hello",
                attachments=["bad"],  # type: ignore[list-item]
            )

    def test_send_result_normalizes_fields(self) -> None:
        result = EmailSendResult(
            message_id="  <id@example.com>  ",
            accepted_recipients=[" to@example.com "],
            rejected_recipients=[" fail@example.com "],
        )

        self.assertEqual(result.message_id, "<id@example.com>")
        self.assertEqual(result.accepted_recipients, ["to@example.com"])
        self.assertEqual(result.rejected_recipients, ["fail@example.com"])

    def test_email_gateway_error_records_metadata(self) -> None:
        cause = RuntimeError("smtp failure")
        error = EmailGatewayError(
            provider="smtp",
            operation="send_email",
            message="failed",
            cause=cause,
        )

        self.assertEqual(str(error), "failed")
        self.assertEqual(error.provider, "smtp")
        self.assertEqual(error.operation, "send_email")
        self.assertIs(error.cause, cause)
