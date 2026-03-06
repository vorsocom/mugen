"""Unit tests for mugen.core.contract.gateway.sms."""

import unittest

from mugen.core.contract.gateway.sms import (
    ISMSGateway,
    SMSGatewayError,
    SMSSendRequest,
    SMSSendResult,
)


class TestMugenContractGatewaySMS(unittest.TestCase):
    """Covers SMS contract validation and normalization behavior."""

    def test_send_request_rejects_blank_or_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            SMSSendRequest(
                to="",
                body="hello",
            )

        with self.assertRaises(ValueError):
            SMSSendRequest(
                to="+15550000001",
                body="   ",
            )

        with self.assertRaises(ValueError):
            SMSSendRequest(
                to=1,  # type: ignore[arg-type]
                body="hello",
            )

        with self.assertRaises(ValueError):
            SMSSendRequest(
                to="+15550000001",
                body="hello",
                from_number=1,  # type: ignore[arg-type]
            )

    def test_send_request_normalizes_optional_fields(self) -> None:
        request = SMSSendRequest(
            to="  +15550000001  ",
            body="  hello world  ",
            from_number="  +15550000002  ",
        )

        self.assertEqual(request.to, "+15550000001")
        self.assertEqual(request.body, "hello world")
        self.assertEqual(request.from_number, "+15550000002")

    def test_send_request_normalizes_blank_from_number_to_none(self) -> None:
        request = SMSSendRequest(
            to="+15550000001",
            body="hello",
            from_number="   ",
        )

        self.assertIsNone(request.from_number)

    def test_send_result_normalizes_fields(self) -> None:
        result = SMSSendResult(
            message_id="  SM123  ",
            recipient="  +15550000001  ",
            provider_status="  queued  ",
        )

        self.assertEqual(result.message_id, "SM123")
        self.assertEqual(result.recipient, "+15550000001")
        self.assertEqual(result.provider_status, "queued")

    def test_send_result_rejects_invalid_recipient(self) -> None:
        with self.assertRaises(ValueError):
            SMSSendResult(
                message_id="SM123",
                recipient="   ",
            )

    def test_sms_gateway_error_records_metadata(self) -> None:
        cause = RuntimeError("twilio failure")
        error = SMSGatewayError(
            provider="twilio",
            operation="send_sms",
            message="failed",
            cause=cause,
        )

        self.assertEqual(str(error), "failed")
        self.assertEqual(error.provider, "twilio")
        self.assertEqual(error.operation, "send_sms")
        self.assertIs(error.cause, cause)

    def test_sms_gateway_interface_is_exposed(self) -> None:
        self.assertTrue(issubclass(ISMSGateway, object))
