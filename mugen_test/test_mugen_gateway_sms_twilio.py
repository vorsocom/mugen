"""Unit tests for mugen.core.gateway.sms.twilio.TwilioSMSGateway."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from mugen.core.contract.gateway.sms import SMSGatewayError, SMSSendRequest
from mugen.core.gateway.sms.twilio import TwilioSMSGateway


def _make_config(
    *,
    account_sid: str = "AC123",
    auth_token: str | None = "auth-token",
    api_key_sid: str | None = None,
    api_key_secret: str | None = None,
    base_url: str = "https://api.twilio.com",
    timeout_seconds: float = 10.0,
    default_from: str | None = None,
    messaging_service_sid: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        twilio=SimpleNamespace(
            api=SimpleNamespace(
                account_sid=account_sid,
                auth_token=auth_token,
                api_key_sid=api_key_sid,
                api_key_secret=api_key_secret,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            ),
            messaging=SimpleNamespace(
                default_from=default_from,
                messaging_service_sid=messaging_service_sid,
            ),
        )
    )


class _FakeResponseContext:
    def __init__(self, *, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(
        self,
        *,
        response: _FakeResponseContext | None = None,
        request_error: Exception | None = None,
        capture: dict[str, object] | None = None,
    ) -> None:
        self._response = response
        self._request_error = request_error
        self._capture = capture if capture is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, method: str, url: str, data=None):
        self._capture["method"] = method
        self._capture["url"] = url
        self._capture["data"] = data
        if self._request_error is not None:
            raise self._request_error
        return self._response


class TestMugenGatewaySMSTwilio(unittest.IsolatedAsyncioTestCase):
    """Coverage for Twilio SMS gateway parsing, readiness, and send behavior."""

    def test_constructor_validates_auth_modes_and_sender_defaults(self) -> None:
        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(SimpleNamespace(), Mock())

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(_make_config(account_sid=123), Mock())  # type: ignore[arg-type]

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(_make_config(account_sid=""), Mock())

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    auth_token="auth-token",
                    api_key_sid="SK123",
                    api_key_secret="secret",
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    auth_token=None,
                    api_key_sid="SK123",
                    api_key_secret=None,
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    auth_token=None,
                    api_key_sid=None,
                    api_key_secret="secret",
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    auth_token=None,
                    api_key_sid=None,
                    api_key_secret=None,
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    auth_token=123,  # type: ignore[arg-type]
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    timeout_seconds="bad",  # type: ignore[arg-type]
                ),
                Mock(),
            )

        with self.assertRaises(SMSGatewayError):
            TwilioSMSGateway(
                _make_config(
                    default_from="+15550000001",
                    messaging_service_sid="MG123",
                ),
                Mock(),
            )

    def test_constructor_uses_api_key_auth_mode(self) -> None:
        gateway = TwilioSMSGateway(
            _make_config(
                auth_token=None,
                api_key_sid="SK123",
                api_key_secret="secret",
            ),
            Mock(),
        )

        self.assertEqual(
            gateway._auth.login, "SK123"
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._auth.password, "secret"
        )  # pylint: disable=protected-access

    async def test_check_readiness_calls_account_probe(self) -> None:
        capture: dict[str, object] = {}
        response = _FakeResponseContext(
            status=200,
            text=json.dumps({"sid": "AC123"}),
        )

        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            side_effect=lambda **kwargs: (
                capture.update({"session_kwargs": kwargs})
                or _FakeSession(response=response, capture=capture)
            ),
        ):
            gateway = TwilioSMSGateway(_make_config(), Mock())
            await gateway.check_readiness()

        self.assertEqual(capture["method"], "GET")
        self.assertEqual(
            capture["url"],
            "https://api.twilio.com/2010-04-01/Accounts/AC123.json",
        )
        self.assertIsInstance(
            capture["session_kwargs"]["timeout"],  # type: ignore[index]
            aiohttp.ClientTimeout,
        )

    async def test_check_readiness_wraps_auth_and_transport_failures(self) -> None:
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                request_error=aiohttp.ClientConnectionError("boom"),
            ),
        ):
            gateway = TwilioSMSGateway(_make_config(), Mock())
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                request_error=asyncio.TimeoutError(),
            ),
        ):
            gateway = TwilioSMSGateway(_make_config(), Mock())
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                response=_FakeResponseContext(
                    status=401,
                    text=json.dumps({"message": "Authenticate"}),
                ),
            ),
        ):
            gateway = TwilioSMSGateway(_make_config(), Mock())
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_check_readiness_rejects_unavailable_configuration(self) -> None:
        gateway = TwilioSMSGateway(_make_config(), Mock())
        gateway._twilio_config = None  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "configuration is unavailable"):
            await gateway.check_readiness()

    async def test_send_sms_uses_request_from_number_override(self) -> None:
        capture: dict[str, object] = {}
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            side_effect=lambda **kwargs: _FakeSession(
                response=_FakeResponseContext(
                    status=201,
                    text=json.dumps(
                        {
                            "sid": "SM123",
                            "to": "+15550000001",
                            "status": "queued",
                        }
                    ),
                ),
                capture=capture,
            ),
        ):
            gateway = TwilioSMSGateway(
                _make_config(default_from="+15550009999"),
                Mock(),
            )
            result = await gateway.send_sms(
                SMSSendRequest(
                    to="+15550000001",
                    body="hello",
                    from_number="+15550000002",
                )
            )

        self.assertEqual(capture["method"], "POST")
        self.assertEqual(
            capture["data"],
            {
                "To": "+15550000001",
                "Body": "hello",
                "From": "+15550000002",
            },
        )
        self.assertEqual(result.message_id, "SM123")
        self.assertEqual(result.recipient, "+15550000001")
        self.assertEqual(result.provider_status, "queued")

    async def test_send_sms_normalizes_non_string_response_fields(self) -> None:
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                response=_FakeResponseContext(
                    status=201,
                    text=json.dumps(
                        {
                            "sid": 123,
                            "to": "   ",
                            "status": 7,
                        }
                    ),
                ),
            ),
        ):
            gateway = TwilioSMSGateway(
                _make_config(default_from="+15550000003"),
                Mock(),
            )
            result = await gateway.send_sms(
                SMSSendRequest(
                    to="+15550000001",
                    body="hello",
                )
            )

        self.assertEqual(result.message_id, "123")
        self.assertEqual(result.recipient, "+15550000001")
        self.assertEqual(result.provider_status, "7")

    async def test_send_sms_uses_configured_default_from(self) -> None:
        capture: dict[str, object] = {}
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                response=_FakeResponseContext(
                    status=201,
                    text=json.dumps({"sid": "SM123", "status": "accepted"}),
                ),
                capture=capture,
            ),
        ):
            gateway = TwilioSMSGateway(
                _make_config(default_from="+15550000003"),
                Mock(),
            )
            await gateway.send_sms(
                SMSSendRequest(
                    to="+15550000001",
                    body="hello",
                )
            )

        self.assertEqual(
            capture["data"],
            {
                "To": "+15550000001",
                "Body": "hello",
                "From": "+15550000003",
            },
        )

    async def test_send_sms_uses_configured_messaging_service_sid(self) -> None:
        capture: dict[str, object] = {}
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                response=_FakeResponseContext(
                    status=201,
                    text=json.dumps({"sid": "SM123", "status": "queued"}),
                ),
                capture=capture,
            ),
        ):
            gateway = TwilioSMSGateway(
                _make_config(
                    default_from=None,
                    messaging_service_sid="MG123",
                ),
                Mock(),
            )
            await gateway.send_sms(
                SMSSendRequest(
                    to="+15550000001",
                    body="hello",
                )
            )

        self.assertEqual(
            capture["data"],
            {
                "To": "+15550000001",
                "Body": "hello",
                "MessagingServiceSid": "MG123",
            },
        )

    async def test_send_sms_requires_sender(self) -> None:
        gateway = TwilioSMSGateway(
            _make_config(default_from=None, messaging_service_sid=None), Mock()
        )

        with self.assertRaisesRegex(SMSGatewayError, "Sender is required"):
            await gateway.send_sms(
                SMSSendRequest(
                    to="+15550000001",
                    body="hello",
                )
            )

    async def test_send_sms_rejects_invalid_request_type(self) -> None:
        gateway = TwilioSMSGateway(_make_config(default_from="+15550000003"), Mock())

        with self.assertRaisesRegex(SMSGatewayError, "SMSSendRequest"):
            await gateway.send_sms("invalid")  # type: ignore[arg-type]

    async def test_send_sms_converts_non_success_response_to_gateway_error(
        self,
    ) -> None:
        with patch(
            "mugen.core.gateway.sms.twilio.aiohttp.ClientSession",
            return_value=_FakeSession(
                response=_FakeResponseContext(
                    status=400,
                    text=json.dumps({"message": "Invalid To number"}),
                ),
            ),
        ):
            gateway = TwilioSMSGateway(
                _make_config(default_from="+15550000003"), Mock()
            )
            with self.assertRaisesRegex(SMSGatewayError, "Invalid To number"):
                await gateway.send_sms(
                    SMSSendRequest(
                        to="+15550000001",
                        body="hello",
                    )
                )

    async def test_send_sms_wraps_unexpected_internal_failure(self) -> None:
        logging_gateway = Mock()
        gateway = TwilioSMSGateway(
            _make_config(default_from="+15550000003"), logging_gateway
        )

        with patch.object(
            gateway,
            "_request_json",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with self.assertRaisesRegex(
                SMSGatewayError, "Unexpected Twilio SMS gateway failure"
            ):
                await gateway.send_sms(
                    SMSSendRequest(
                        to="+15550000001",
                        body="hello",
                    )
                )

        logging_gateway.warning.assert_called_once()

    def test_parse_success_payload_edge_cases(self) -> None:
        gateway = TwilioSMSGateway(_make_config(default_from="+15550000003"), Mock())

        self.assertEqual(
            gateway._parse_success_payload(  # pylint: disable=protected-access
                "   ",
                operation="send_sms",
            ),
            {},
        )

        with self.assertRaisesRegex(SMSGatewayError, "invalid JSON"):
            gateway._parse_success_payload(  # pylint: disable=protected-access
                "{bad",
                operation="send_sms",
            )

        with self.assertRaisesRegex(SMSGatewayError, "invalid response payload"):
            gateway._parse_success_payload(  # pylint: disable=protected-access
                '["not-a-dict"]',
                operation="send_sms",
            )

    def test_extract_error_message_edge_cases(self) -> None:
        self.assertEqual(
            TwilioSMSGateway._extract_error_message("   "), "Empty response body."
        )
        self.assertEqual(
            TwilioSMSGateway._extract_error_message("not json"), "not json"
        )
        self.assertEqual(TwilioSMSGateway._extract_error_message("[]"), "[]")
        self.assertEqual(
            TwilioSMSGateway._extract_error_message('{"message":"   "}'),
            '{"message":"   "}',
        )
