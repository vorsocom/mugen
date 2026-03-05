"""Provides an implementation of ISignalClient."""

__all__ = ["DefaultSignalClient", "SignalAPIResponse"]

import asyncio
from collections.abc import AsyncIterator, Callable
import fnmatch
from http import HTTPMethod
import json
import mimetypes
import tempfile
from types import SimpleNamespace
from typing import TypedDict
from urllib.parse import quote
import uuid

import aiohttp

from mugen.core.contract.client.signal import ISignalClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


class SignalAPIResponse(TypedDict):
    """Represents a normalized Signal API response envelope."""

    ok: bool
    status: int | None
    data: dict | list | None
    error: str | None
    raw: str | None


class DefaultSignalClient(ISignalClient):  # pylint: disable=too-many-instance-attributes
    """An implementation of ISignalClient."""

    _default_http_timeout_seconds: float = 10.0
    _default_max_api_retries: int = 2
    _default_retry_backoff_seconds: float = 0.5
    _default_receive_heartbeat_seconds: float = 30.0
    _default_max_download_bytes: int = 20 * 1024 * 1024
    _default_typing_enabled: bool = True

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._client_session: aiohttp.ClientSession | None = None
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service
        self._http_timeout_seconds = self._resolve_http_timeout_seconds()
        self._max_api_retries = self._resolve_max_api_retries()
        self._retry_backoff_seconds = self._resolve_retry_backoff_seconds()
        self._receive_heartbeat_seconds = self._resolve_receive_heartbeat_seconds()
        self._max_download_bytes = self._resolve_max_download_bytes()
        self._typing_enabled = self._resolve_typing_enabled()
        self._shutdown_timeout_seconds = self._resolve_shutdown_timeout_seconds()
        self._api_base_url = str(self._config.signal.api.base_url).rstrip("/")
        self._account_number = str(self._config.signal.account.number).strip()
        self._bearer_token = str(self._config.signal.api.bearer_token).strip()
        self._allowed_mimetypes = [
            str(item).strip()
            for item in list(self._config.signal.media.allowed_mimetypes)
            if isinstance(item, str) and item.strip() != ""
        ]

    def _resolve_http_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "signal", None), "api", None),
            "timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "signal.api.timeout_seconds",
        )
        if timeout is None:
            return self._default_http_timeout_seconds
        return timeout

    def _resolve_max_api_retries(self) -> int:
        raw_retries = getattr(
            getattr(getattr(self._config, "signal", None), "api", None),
            "max_api_retries",
            self._default_max_api_retries,
        )
        try:
            retries = int(raw_retries)
        except (TypeError, ValueError):
            retries = self._default_max_api_retries
        if retries < 0:
            return self._default_max_api_retries
        return retries

    def _resolve_retry_backoff_seconds(self) -> float:
        raw_backoff = getattr(
            getattr(getattr(self._config, "signal", None), "api", None),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_backoff,
            field_name="signal.api.retry_backoff_seconds",
            default=self._default_retry_backoff_seconds,
        )

    def _resolve_receive_heartbeat_seconds(self) -> float:
        raw_heartbeat = getattr(
            getattr(getattr(self._config, "signal", None), "receive", None),
            "heartbeat_seconds",
            None,
        )
        heartbeat = parse_optional_positive_finite_float(
            raw_heartbeat,
            "signal.receive.heartbeat_seconds",
        )
        if heartbeat is None:
            return self._default_receive_heartbeat_seconds
        return heartbeat

    def _resolve_max_download_bytes(self) -> int:
        raw_limit = getattr(
            getattr(getattr(self._config, "signal", None), "media", None),
            "max_download_bytes",
            self._default_max_download_bytes,
        )
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = self._default_max_download_bytes
        if limit <= 0:
            return self._default_max_download_bytes
        return limit

    def _resolve_typing_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "signal", None), "typing", None),
            "enabled",
            self._default_typing_enabled,
        )
        return parse_bool_flag(raw_enabled, self._default_typing_enabled)

    def _resolve_shutdown_timeout_seconds(self) -> float:
        settings = parse_runtime_bootstrap_settings(self._config)
        return float(settings.shutdown_timeout_seconds)

    @staticmethod
    def _parse_response_payload(response_text: str | None) -> dict | list | None:
        if response_text in [None, ""]:
            return None
        try:
            parsed = json.loads(response_text)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, dict | list):
            return parsed
        return None

    @staticmethod
    def _build_api_response(
        *,
        ok: bool,
        status: int | None,
        data: dict | list | None = None,
        error: str | None = None,
        raw: str | None = None,
    ) -> SignalAPIResponse:
        return {
            "ok": ok,
            "status": status,
            "data": data,
            "error": error,
            "raw": raw,
        }

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        return status == 429 or status >= 500

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex

    async def _wait_before_retry(
        self,
        *,
        attempt: int,
        correlation_id: str,
        method: str,
        path: str,
        reason: str,
    ) -> None:
        delay_seconds = self._retry_backoff_seconds * (2**attempt)
        self._logging_gateway.warning(
            f"[cid={correlation_id}] Retrying Signal API call for {method} {path} in "
            f"{delay_seconds:.2f}s ({reason}) attempt={attempt + 1}."
        )
        await asyncio.sleep(delay_seconds)

    def _auth_headers(self, *, json_content: bool = True) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._bearer_token}",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _normalize_recipient(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if normalized == "":
            return None
        return normalized

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultSignalClient.init")
        if self._client_session is not None and self._client_session.closed is False:
            return
        timeout = aiohttp.ClientTimeout(total=self._http_timeout_seconds)
        self._client_session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultSignalClient.close")
        if self._client_session is None:
            return
        if self._client_session.closed is True:
            return
        try:
            await asyncio.wait_for(
                self._client_session.close(),
                timeout=self._shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "Signal client shutdown timed out while closing HTTP session."
            ) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Signal client shutdown failed while closing HTTP session."
            ) from exc

    async def _call_api(
        self,
        path: str,
        *,
        method: HTTPMethod = HTTPMethod.POST,
        payload: dict | None = None,
    ) -> SignalAPIResponse:
        if self._client_session is None or self._client_session.closed is True:
            await self.init()

        request_fn: Callable = getattr(
            self._client_session,  # type: ignore[union-attr]
            method.value.lower(),
            None,
        )
        if callable(request_fn) is not True:
            return self._build_api_response(
                ok=False,
                status=None,
                error=f"Unsupported HTTP method: {method.value}",
            )

        url = f"{self._api_base_url}{path}"
        correlation_id = self._new_correlation_id()
        kwargs: dict = {
            "headers": self._auth_headers(json_content=True),
        }
        if payload is not None:
            kwargs["json"] = payload

        for attempt in range(self._max_api_retries + 1):
            try:
                response = await request_fn(url, **kwargs)
                response_text = await response.text()
                parsed_payload = self._parse_response_payload(response_text)
                status = response.status
                if 200 <= status < 300:
                    return self._build_api_response(
                        ok=True,
                        status=status,
                        data=parsed_payload,
                        raw=response_text,
                    )

                should_retry = (
                    attempt < self._max_api_retries
                    and self._is_retryable_status(status)
                )
                if should_retry:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=correlation_id,
                        method=method.value,
                        path=path,
                        reason=f"status={status}",
                    )
                    continue

                error_message = None
                if isinstance(parsed_payload, dict):
                    error_value = parsed_payload.get("error")
                    if isinstance(error_value, str) and error_value.strip() != "":
                        error_message = error_value.strip()
                if error_message in [None, ""]:
                    error_message = (
                        f"Signal API call failed for {method.value} {path} "
                        f"(status={status})."
                    )
                return self._build_api_response(
                    ok=False,
                    status=status,
                    data=parsed_payload,
                    error=error_message,
                    raw=response_text,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                should_retry = attempt < self._max_api_retries
                if should_retry:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=correlation_id,
                        method=method.value,
                        path=path,
                        reason=f"error={type(exc).__name__}",
                    )
                    continue
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error=(
                        f"Signal API request error for {method.value} {path}: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

        return self._build_api_response(
            ok=False,
            status=None,
            error=f"Signal API call failed for {method.value} {path}.",
        )

    async def verify_startup(self) -> bool:
        self._logging_gateway.debug("DefaultSignalClient.verify_startup")
        health = await self._call_api(
            "/v1/health",
            method=HTTPMethod.GET,
        )
        if health.get("ok") is not True:
            return False

        about = await self._call_api(
            "/v1/about",
            method=HTTPMethod.GET,
        )
        if about.get("ok") is not True:
            return False

        about_data = about.get("data")
        if not isinstance(about_data, dict):
            return False
        mode = str(about_data.get("mode", "")).strip().lower()
        return mode == "json-rpc"

    async def receive_events(self) -> AsyncIterator[dict]:
        if self._client_session is None or self._client_session.closed is True:
            await self.init()

        path_number = quote(self._account_number, safe="")
        ws_url = f"{self._api_base_url}/v1/receive/{path_number}"
        ws_timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self._http_timeout_seconds,
            sock_connect=self._http_timeout_seconds,
            sock_read=None,
        )
        async with self._client_session.ws_connect(  # type: ignore[union-attr]
            ws_url,
            heartbeat=self._receive_heartbeat_seconds,
            timeout=ws_timeout,
            headers=self._auth_headers(json_content=False),
        ) as websocket:
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    parsed = self._parse_response_payload(message.data)
                    if isinstance(parsed, dict):
                        yield parsed
                    else:
                        self._logging_gateway.warning(
                            "Signal websocket payload is not an object."
                        )
                    continue

                if message.type == aiohttp.WSMsgType.ERROR:
                    error = websocket.exception()
                    raise RuntimeError(
                        "Signal receive websocket error: "
                        f"{type(error).__name__ if error else 'unknown'}: {error}"
                    )

                if message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    raise RuntimeError("Signal receive websocket closed.")

                self._logging_gateway.debug(
                    f"Signal websocket message ignored (type={message.type})."
                )

        raise RuntimeError("Signal receive websocket disconnected.")

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
    ) -> dict | None:
        normalized_recipient = self._normalize_recipient(recipient)
        if normalized_recipient is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal send text requires a non-empty recipient.",
            )
        if not isinstance(text, str) or text.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal send text requires a non-empty text payload.",
            )

        return await self._call_api(
            "/v2/send",
            method=HTTPMethod.POST,
            payload={
                "number": self._account_number,
                "message": text,
                "recipients": [normalized_recipient],
            },
        )

    async def send_media_message(
        self,
        *,
        recipient: str,
        message: str | None = None,
        base64_attachments: list[str] | None = None,
    ) -> dict | None:
        normalized_recipient = self._normalize_recipient(recipient)
        if normalized_recipient is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal send media requires a non-empty recipient.",
            )
        attachments = [
            item
            for item in list(base64_attachments or [])
            if isinstance(item, str) and item.strip() != ""
        ]
        if not attachments:
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal send media requires at least one base64 attachment.",
            )

        payload = {
            "number": self._account_number,
            "recipients": [normalized_recipient],
            "base64_attachments": attachments,
        }
        if isinstance(message, str) and message.strip() != "":
            payload["message"] = message

        return await self._call_api(
            "/v2/send",
            method=HTTPMethod.POST,
            payload=payload,
        )

    async def send_reaction(
        self,
        *,
        recipient: str,
        reaction: str,
        target_author: str,
        timestamp: int,
        remove: bool = False,
    ) -> dict | None:
        normalized_recipient = self._normalize_recipient(recipient)
        normalized_author = self._normalize_recipient(target_author)
        if normalized_recipient is None or normalized_author is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal reaction requires non-empty recipient and target_author.",
            )
        if not isinstance(reaction, str) or reaction.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal reaction requires a non-empty reaction.",
            )

        number = quote(self._account_number, safe="")
        method = HTTPMethod.DELETE if remove else HTTPMethod.POST
        return await self._call_api(
            f"/v1/reactions/{number}",
            method=method,
            payload={
                "recipient": normalized_recipient,
                "reaction": reaction.strip(),
                "target_author": normalized_author,
                "timestamp": int(timestamp),
            },
        )

    async def send_receipt(
        self,
        *,
        recipient: str,
        receipt_type: str,
        timestamp: int,
    ) -> dict | None:
        normalized_recipient = self._normalize_recipient(recipient)
        if normalized_recipient is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal receipt requires a non-empty recipient.",
            )
        if not isinstance(receipt_type, str) or receipt_type.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="Signal receipt requires a non-empty receipt_type.",
            )

        number = quote(self._account_number, safe="")
        return await self._call_api(
            f"/v1/receipts/{number}",
            method=HTTPMethod.POST,
            payload={
                "recipient": normalized_recipient,
                "receipt_type": receipt_type.strip().lower(),
                "timestamp": int(timestamp),
            },
        )

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = message_id
        if self._typing_enabled is not True:
            return None

        normalized_recipient = self._normalize_recipient(recipient)
        if normalized_recipient is None:
            return False

        try:
            normalized_state = normalize_processing_state(state)
        except ValueError:
            return False
        number = quote(self._account_number, safe="")
        method = (
            HTTPMethod.PUT
            if normalized_state == PROCESSING_STATE_START
            else HTTPMethod.DELETE
        )
        if normalized_state not in {PROCESSING_STATE_START, PROCESSING_STATE_STOP}:
            return False

        response = await self._call_api(
            f"/v1/typing-indicator/{number}",
            method=method,
            payload={"recipient": normalized_recipient},
        )
        return bool(response.get("ok"))

    def _mime_type_allowed(self, mime_type: str) -> bool:
        if not self._allowed_mimetypes:
            return True
        return any(
            fnmatch.fnmatch(mime_type, pattern)
            for pattern in self._allowed_mimetypes
        )

    async def download_attachment(self, attachment_id: str) -> dict[str, object] | None:
        normalized_id = self._normalize_recipient(attachment_id)
        if normalized_id is None:
            return None
        if self._client_session is None or self._client_session.closed is True:
            await self.init()

        url = (
            f"{self._api_base_url}/v1/attachments/{quote(normalized_id, safe='')}"
        )
        try:
            response = await self._client_session.get(  # type: ignore[union-attr]
                url,
                headers=self._auth_headers(json_content=False),
            )
            if response.status != 200:
                return None

            content_type = str(
                response.headers.get("Content-Type", "application/octet-stream")
            ).split(";")[0].strip().lower()
            if content_type == "":
                content_type = "application/octet-stream"
            if self._mime_type_allowed(content_type) is not True:
                return None

            payload = await response.read()
            if len(payload) > self._max_download_bytes:
                return None

            ext = mimetypes.guess_extension(content_type) or ".bin"
            with tempfile.NamedTemporaryFile(
                prefix="signal_media_",
                suffix=ext,
                delete=False,
            ) as handle:
                handle.write(payload)
                path = handle.name

            return {
                "path": path,
                "mime_type": content_type,
                "size_bytes": len(payload),
            }
        except Exception:  # pylint: disable=broad-exception-caught
            return None
