"""Provides a Twilio outbound SMS gateway."""

__all__ = ["TwilioSMSGateway"]

import asyncio
from http import HTTPMethod
import json
from types import SimpleNamespace
from typing import Any

import aiohttp

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.sms import (
    ISMSGateway,
    SMSGatewayError,
    SMSSendRequest,
    SMSSendResult,
)
from mugen.core.utility.config_value import parse_optional_positive_finite_float


class TwilioSMSGateway(ISMSGateway):  # pylint: disable=too-few-public-methods
    """A Twilio-based outbound SMS gateway."""

    _provider = "twilio"
    _default_timeout_seconds = 10.0

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._twilio_config = self._resolve_twilio_config()
        self._auth = self._build_auth()

    async def check_readiness(self) -> None:
        if not isinstance(self._twilio_config, dict):
            raise RuntimeError("Twilio SMS gateway configuration is unavailable.")

        try:
            await self._request_json(
                operation="check_readiness",
                method=HTTPMethod.GET,
                path=(
                    f"/2010-04-01/Accounts/"
                    f"{self._twilio_config['account_sid']}.json"
                ),
            )
        except SMSGatewayError as exc:
            raise RuntimeError("Twilio SMS gateway readiness probe failed.") from exc

    async def send_sms(self, request: SMSSendRequest) -> SMSSendResult:
        if not isinstance(request, SMSSendRequest):
            raise SMSGatewayError(
                provider=self._provider,
                operation="send_sms",
                message="request must be an SMSSendRequest instance.",
            )

        payload = {
            "To": request.to,
            "Body": request.body,
        }
        sender_field, sender_value = self._resolve_sender(request)
        payload[sender_field] = sender_value

        try:
            response_payload = await self._request_json(
                operation="send_sms",
                method=HTTPMethod.POST,
                path=(
                    f"/2010-04-01/Accounts/"
                    f"{self._twilio_config['account_sid']}/Messages.json"
                ),
                data=payload,
            )
        except SMSGatewayError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "TwilioSMSGateway.send_sms: "
                "Unexpected failure while processing outbound SMS request."
            )
            raise SMSGatewayError(
                provider=self._provider,
                operation="send_sms",
                message="Unexpected Twilio SMS gateway failure.",
                cause=exc,
            ) from exc

        message_id = response_payload.get("sid")
        if message_id is not None and not isinstance(message_id, str):
            message_id = str(message_id)

        recipient = response_payload.get("to")
        if not isinstance(recipient, str) or recipient.strip() == "":
            recipient = request.to

        provider_status = response_payload.get("status")
        if provider_status is not None and not isinstance(provider_status, str):
            provider_status = str(provider_status)

        return SMSSendResult(
            message_id=message_id,
            recipient=recipient,
            provider_status=provider_status,
        )

    async def _request_json(
        self,
        *,
        operation: str,
        method: HTTPMethod,
        path: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=self._twilio_config["timeout_seconds"])
        url = f"{self._twilio_config['base_url']}{path}"

        try:
            async with aiohttp.ClientSession(
                auth=self._auth,
                timeout=timeout,
            ) as client:
                async with client.request(
                    method.value,
                    url,
                    data=data,
                ) as response:
                    response_text = await response.text()
                    if 200 <= response.status < 300:
                        return self._parse_success_payload(
                            response_text,
                            operation=operation,
                        )
                    raise SMSGatewayError(
                        provider=self._provider,
                        operation=operation,
                        message=(
                            f"Twilio SMS provider error ({response.status}): "
                            f"{self._extract_error_message(response_text)}"
                        ),
                    )
        except SMSGatewayError:
            raise
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as exc:
            raise SMSGatewayError(
                provider=self._provider,
                operation=operation,
                message="Twilio SMS transport timed out.",
                cause=exc,
            ) from exc
        except aiohttp.ClientError as exc:
            raise SMSGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Twilio SMS transport error: {exc}",
                cause=exc,
            ) from exc

    def _parse_success_payload(
        self,
        response_text: str,
        *,
        operation: str,
    ) -> dict[str, Any]:
        stripped = response_text.strip()
        if stripped == "":
            return {}

        try:
            payload = json.loads(stripped)
        except ValueError as exc:
            raise SMSGatewayError(
                provider=self._provider,
                operation=operation,
                message="Twilio SMS provider returned invalid JSON.",
                cause=exc,
            ) from exc

        if not isinstance(payload, dict):
            raise SMSGatewayError(
                provider=self._provider,
                operation=operation,
                message="Twilio SMS provider returned an invalid response payload.",
            )

        return payload

    @staticmethod
    def _extract_error_message(response_text: str) -> str:
        stripped = response_text.strip()
        if stripped == "":
            return "Empty response body."

        try:
            payload = json.loads(stripped)
        except ValueError:
            return stripped

        if not isinstance(payload, dict):
            return stripped

        message = payload.get("message")
        if isinstance(message, str) and message.strip() != "":
            return message.strip()

        return stripped

    def _resolve_sender(self, request: SMSSendRequest) -> tuple[str, str]:
        if request.from_number is not None:
            return "From", request.from_number

        default_from = self._twilio_config["default_from"]
        if default_from is not None:
            return "From", default_from

        messaging_service_sid = self._twilio_config["messaging_service_sid"]
        if messaging_service_sid is not None:
            return "MessagingServiceSid", messaging_service_sid

        raise SMSGatewayError(
            provider=self._provider,
            operation="send_sms",
            message=(
                "Sender is required. Provide request.from_number or configure "
                "twilio.messaging.default_from or "
                "twilio.messaging.messaging_service_sid."
            ),
        )

    def _build_auth(self) -> aiohttp.BasicAuth:
        api_key_sid = self._twilio_config["api_key_sid"]
        api_key_secret = self._twilio_config["api_key_secret"]
        if api_key_sid is not None and api_key_secret is not None:
            return aiohttp.BasicAuth(login=api_key_sid, password=api_key_secret)

        return aiohttp.BasicAuth(
            login=self._twilio_config["account_sid"],
            password=self._twilio_config["auth_token"],
        )

    def _resolve_twilio_config(self) -> dict[str, object]:
        try:
            twilio_cfg = self._config.twilio
            api_cfg = twilio_cfg.api
            messaging_cfg = twilio_cfg.messaging
        except AttributeError as exc:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message="Missing Twilio configuration section: [twilio].",
                cause=exc,
            ) from exc

        account_sid = self._required_string(
            getattr(api_cfg, "account_sid", None),
            "twilio.api.account_sid",
        )
        auth_token = self._optional_string(
            getattr(api_cfg, "auth_token", None),
            "twilio.api.auth_token",
        )
        api_key_sid = self._optional_string(
            getattr(api_cfg, "api_key_sid", None),
            "twilio.api.api_key_sid",
        )
        api_key_secret = self._optional_string(
            getattr(api_cfg, "api_key_secret", None),
            "twilio.api.api_key_secret",
        )

        has_auth_token = auth_token is not None
        has_api_key_pair = api_key_sid is not None or api_key_secret is not None
        if has_auth_token and has_api_key_pair:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "Twilio auth must use exactly one mode: auth_token or "
                    "api_key_sid/api_key_secret."
                ),
            )
        if api_key_sid is None and api_key_secret is not None:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "twilio.api.api_key_sid and twilio.api.api_key_secret must be "
                    "configured together."
                ),
            )
        if api_key_sid is not None and api_key_secret is None:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "twilio.api.api_key_sid and twilio.api.api_key_secret must be "
                    "configured together."
                ),
            )
        if not has_auth_token and not (
            api_key_sid is not None and api_key_secret is not None
        ):
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "Twilio auth requires either twilio.api.auth_token or "
                    "twilio.api.api_key_sid/twilio.api.api_key_secret."
                ),
            )

        base_url = self._required_string(
            getattr(api_cfg, "base_url", "https://api.twilio.com"),
            "twilio.api.base_url",
        ).rstrip("/")
        timeout_seconds = getattr(
            api_cfg, "timeout_seconds", self._default_timeout_seconds
        )
        try:
            parsed_timeout = parse_optional_positive_finite_float(
                timeout_seconds,
                "twilio.api.timeout_seconds",
            )
        except RuntimeError as exc:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=str(exc).replace("Invalid configuration: ", ""),
                cause=exc,
            ) from exc
        timeout_seconds = (
            self._default_timeout_seconds if parsed_timeout is None else parsed_timeout
        )

        default_from = self._optional_string(
            getattr(messaging_cfg, "default_from", None),
            "twilio.messaging.default_from",
        )
        messaging_service_sid = self._optional_string(
            getattr(messaging_cfg, "messaging_service_sid", None),
            "twilio.messaging.messaging_service_sid",
        )
        if default_from is not None and messaging_service_sid is not None:
            raise SMSGatewayError(
                provider=self._provider,
                operation="initialization",
                message=(
                    "twilio.messaging.default_from and "
                    "twilio.messaging.messaging_service_sid are mutually exclusive."
                ),
            )

        return {
            "account_sid": account_sid,
            "auth_token": auth_token,
            "api_key_sid": api_key_sid,
            "api_key_secret": api_key_secret,
            "base_url": base_url,
            "timeout_seconds": timeout_seconds,
            "default_from": default_from,
            "messaging_service_sid": messaging_service_sid,
        }

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise SMSGatewayError(
                provider="twilio",
                operation="initialization",
                message=f"{field_name} must be a string.",
            )

        stripped = value.strip()
        if stripped == "":
            raise SMSGatewayError(
                provider="twilio",
                operation="initialization",
                message=f"{field_name} must be a non-empty string.",
            )

        return stripped

    @staticmethod
    def _optional_string(value: object, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise SMSGatewayError(
                provider="twilio",
                operation="initialization",
                message=f"{field_name} must be a string when provided.",
            )

        stripped = value.strip()
        if stripped == "":
            return None

        return stripped
