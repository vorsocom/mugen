"""Provides an implementation of ILineClient."""

__all__ = ["DefaultLineClient", "LineAPIResponse"]

import asyncio
import fnmatch
from http import HTTPMethod
import json
import mimetypes
import os
import tempfile
from types import SimpleNamespace
from typing import Any, TypedDict
import uuid

import aiohttp

from mugen.core.contract.client.line import ILineClient
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
    normalize_processing_state,
)


class LineAPIResponse(TypedDict):
    """Represents a normalized LINE Messaging API response envelope."""

    ok: bool
    status: int | None
    data: dict[str, Any] | None
    error: str | None
    raw: str | None


# pylint: disable=too-many-instance-attributes
class DefaultLineClient(ILineClient):
    """Default LINE Messaging API adapter."""

    _default_api_base_url: str = "https://api.line.me"

    _default_http_timeout_seconds: float = 10.0

    _default_max_download_bytes: int = 20 * 1024 * 1024

    _default_max_api_retries: int = 2

    _default_retry_backoff_seconds: float = 0.5

    _default_typing_enabled: bool = True

    _default_allowed_mimetypes: tuple[str, ...] = (
        "audio/*",
        "image/*",
        "video/*",
        "application/*",
        "text/*",
    )

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        ipc_service: IIPCService | None = None,
        keyval_storage_gateway: IKeyValStorageGateway | None = None,
        logging_gateway: ILoggingGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
    ) -> None:
        self._client_session: aiohttp.ClientSession | None = None
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        self._api_base_url = self._resolve_api_base_url()
        self._access_token = self._resolve_access_token()
        self._http_timeout_seconds = self._resolve_http_timeout_seconds()
        self._max_download_bytes = self._resolve_max_download_bytes()
        self._max_api_retries = self._resolve_max_api_retries()
        self._retry_backoff_seconds = self._resolve_retry_backoff_seconds()
        self._typing_enabled = self._resolve_typing_enabled()
        self._allowed_mimetypes = self._resolve_allowed_mimetypes()
        self._shutdown_timeout_seconds = self._resolve_shutdown_timeout_seconds()

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex

    def _resolve_api_base_url(self) -> str:
        raw_base_url = getattr(
            getattr(getattr(self._config, "line", None), "api", None),
            "base_url",
            self._default_api_base_url,
        )
        if not isinstance(raw_base_url, str) or raw_base_url.strip() == "":
            return self._default_api_base_url
        return raw_base_url.strip().rstrip("/")

    def _resolve_access_token(self) -> str:
        token = getattr(
            getattr(getattr(self._config, "line", None), "channel", None),
            "access_token",
            "",
        )
        return str(token or "").strip()

    def _resolve_http_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "line", None), "api", None),
            "timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "line.api.timeout_seconds",
        )
        if timeout is None:
            return self._default_http_timeout_seconds
        return timeout

    def _resolve_max_download_bytes(self) -> int:
        raw_limit = getattr(
            getattr(getattr(self._config, "line", None), "media", None),
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

    def _resolve_max_api_retries(self) -> int:
        raw_retries = getattr(
            getattr(getattr(self._config, "line", None), "api", None),
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
            getattr(getattr(self._config, "line", None), "api", None),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_backoff,
            field_name="line.api.retry_backoff_seconds",
            default=self._default_retry_backoff_seconds,
        )

    def _resolve_typing_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "line", None), "typing", None),
            "enabled",
            self._default_typing_enabled,
        )
        return parse_bool_flag(raw_enabled, self._default_typing_enabled)

    def _resolve_allowed_mimetypes(self) -> tuple[str, ...]:
        raw_allowed = getattr(
            getattr(getattr(self._config, "line", None), "media", None),
            "allowed_mimetypes",
            list(self._default_allowed_mimetypes),
        )
        if not isinstance(raw_allowed, list):
            return self._default_allowed_mimetypes

        normalized: list[str] = []
        for item in raw_allowed:
            if not isinstance(item, str):
                continue
            candidate = item.strip().lower()
            if candidate == "" or candidate in normalized:
                continue
            normalized.append(candidate)

        if not normalized:
            return self._default_allowed_mimetypes

        return tuple(normalized)

    def _resolve_shutdown_timeout_seconds(self) -> float:
        settings = parse_runtime_bootstrap_settings(self._config)
        return float(settings.shutdown_timeout_seconds)

    @staticmethod
    def _parse_response_payload(response_text: str | None) -> dict[str, Any] | None:
        if response_text in [None, ""]:
            return None

        try:
            parsed = json.loads(response_text)
        except (TypeError, ValueError):
            return None

        if isinstance(parsed, dict):
            return parsed

        return None

    @staticmethod
    def _build_api_response(
        *,
        ok: bool,
        status: int | None,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        raw: str | None = None,
    ) -> LineAPIResponse:
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

    def _resolve_correlation_id(self, correlation_id: str | None) -> str:
        if isinstance(correlation_id, str) and correlation_id != "":
            return correlation_id
        return self._new_correlation_id()

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
            f"[cid={correlation_id}] Retrying LINE API call for {method} {path} in "
            f"{delay_seconds:.2f}s ({reason}) attempt={attempt + 1}."
        )
        await asyncio.sleep(delay_seconds)

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _response_error_text(payload: dict[str, Any] | None, *, fallback: str) -> str:
        if not isinstance(payload, dict):
            return fallback

        message = payload.get("message")
        if isinstance(message, str) and message.strip() != "":
            details = payload.get("details")
            if isinstance(details, list) and details:
                return f"{message.strip()} ({details})"
            return message.strip()

        return fallback

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultLineClient.init")
        if (
            self._client_session is not None
            and getattr(self._client_session, "closed", False) is False
        ):
            return

        timeout = aiohttp.ClientTimeout(total=self._http_timeout_seconds)
        self._client_session = aiohttp.ClientSession(timeout=timeout)

    async def verify_startup(self) -> bool:
        correlation_id = self._new_correlation_id()
        probe_response = await self._call_api(
            path="/v2/bot/info",
            method=HTTPMethod.GET,
            correlation_id=correlation_id,
        )
        if (
            isinstance(probe_response, dict)
            and probe_response.get("ok") is True
            and isinstance(probe_response.get("status"), int)
            and 200 <= int(probe_response.get("status")) < 300
        ):
            return True

        status = probe_response.get("status") if isinstance(probe_response, dict) else None
        error = (
            probe_response.get("error")
            if isinstance(probe_response, dict)
            else "startup probe returned unexpected payload"
        )
        self._logging_gateway.error(
            f"[cid={correlation_id}] LINE startup probe failed "
            f"status={status} error={error!r}."
        )
        return False

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultLineClient.close")
        if self._client_session is None:
            return

        if getattr(self._client_session, "closed", False) is True:
            self._client_session = None
            return

        try:
            await asyncio.wait_for(
                self._client_session.close(),
                timeout=self._shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._logging_gateway.error("LINE client session close timed out.")
            raise RuntimeError("LINE client session close timed out.") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "LINE client session close failed "
                f"error_type={type(exc).__name__} error={exc}"
            )
            raise RuntimeError(
                f"LINE client session close failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            self._client_session = None

    async def _call_api(
        self,
        *,
        path: str,
        method: HTTPMethod,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> LineAPIResponse:
        correlation_id = self._resolve_correlation_id(correlation_id)
        request_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._api_base_url}{request_path}"
        max_attempts = self._max_api_retries + 1

        for attempt in range(max_attempts):
            try:
                if self._client_session is None or self._client_session.closed:
                    await self.init()

                response = await self._client_session.request(
                    method=method.value,
                    url=url,
                    json=payload,
                    headers=self._request_headers(),
                )
                try:
                    response_text = await response.text()
                    parsed = self._parse_response_payload(response_text)
                    if 200 <= response.status < 300:
                        return self._build_api_response(
                            ok=True,
                            status=response.status,
                            data=parsed if isinstance(parsed, dict) else {},
                            raw=response_text,
                        )

                    if (
                        attempt < self._max_api_retries
                        and self._is_retryable_status(response.status)
                    ):
                        await self._wait_before_retry(
                            attempt=attempt,
                            correlation_id=correlation_id,
                            method=method.value,
                            path=request_path,
                            reason=f"status={response.status}",
                        )
                        continue

                    error_message = self._response_error_text(
                        parsed,
                        fallback=(
                            "LINE API call failed "
                            f"status={response.status}"
                        ),
                    )
                    return self._build_api_response(
                        ok=False,
                        status=response.status,
                        data=parsed,
                        error=error_message,
                        raw=response_text,
                    )
                finally:
                    response.release()
                    response.close()
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt < self._max_api_retries:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=correlation_id,
                        method=method.value,
                        path=request_path,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error=f"{type(exc).__name__}: {exc}",
                )

        return self._build_api_response(
            ok=False,
            status=None,
            error="LINE API request exhausted retries.",
        )

    async def reply_messages(
        self,
        *,
        reply_token: str,
        messages: list[dict[str, Any]],
    ) -> dict | None:
        if not isinstance(reply_token, str) or reply_token.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="reply_token is required.",
            )
        if not isinstance(messages, list) or not messages:
            return self._build_api_response(
                ok=False,
                status=None,
                error="messages is required.",
            )
        return await self._call_api(
            path="/v2/bot/message/reply",
            method=HTTPMethod.POST,
            payload={
                "replyToken": reply_token.strip(),
                "messages": messages,
            },
            correlation_id=reply_token.strip(),
        )

    async def push_messages(
        self,
        *,
        to: str,
        messages: list[dict[str, Any]],
    ) -> dict | None:
        if not isinstance(to, str) or to.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="push recipient is required.",
            )
        if not isinstance(messages, list) or not messages:
            return self._build_api_response(
                ok=False,
                status=None,
                error="messages is required.",
            )
        return await self._call_api(
            path="/v2/bot/message/push",
            method=HTTPMethod.POST,
            payload={
                "to": to.strip(),
                "messages": messages,
            },
            correlation_id=to.strip(),
        )

    async def multicast_messages(
        self,
        *,
        to: list[str],
        messages: list[dict[str, Any]],
    ) -> dict | None:
        if not isinstance(to, list) or not to:
            return self._build_api_response(
                ok=False,
                status=None,
                error="multicast recipients are required.",
            )
        recipients = [str(value).strip() for value in to if str(value).strip() != ""]
        if not recipients:
            return self._build_api_response(
                ok=False,
                status=None,
                error="multicast recipients are required.",
            )
        if not isinstance(messages, list) or not messages:
            return self._build_api_response(
                ok=False,
                status=None,
                error="messages is required.",
            )

        return await self._call_api(
            path="/v2/bot/message/multicast",
            method=HTTPMethod.POST,
            payload={
                "to": recipients,
                "messages": messages,
            },
            correlation_id=recipients[0],
        )

    @staticmethod
    def _coerce_https_url(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if candidate == "":
            return None
        if candidate.startswith("https://") is not True:
            return None
        return candidate

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_token: str | None = None,
    ) -> dict | None:
        if not isinstance(text, str) or text.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error="text is required.",
            )

        message_payload = [{"type": "text", "text": text}]
        if isinstance(reply_token, str) and reply_token.strip() != "":
            return await self.reply_messages(
                reply_token=reply_token,
                messages=message_payload,
            )

        return await self.push_messages(
            to=recipient,
            messages=message_payload,
        )

    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        url = self._coerce_https_url(image.get("url"))
        if url is None:
            url = self._coerce_https_url(image.get("original_content_url"))
        preview_url = self._coerce_https_url(image.get("preview_url"))
        if preview_url is None:
            preview_url = self._coerce_https_url(image.get("preview_image_url"))
        if preview_url is None:
            preview_url = url

        if url is None or preview_url is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="LINE image message requires HTTPS URL fields.",
            )

        message_payload = [
            {
                "type": "image",
                "originalContentUrl": url,
                "previewImageUrl": preview_url,
            }
        ]
        if isinstance(reply_token, str) and reply_token.strip() != "":
            return await self.reply_messages(
                reply_token=reply_token,
                messages=message_payload,
            )

        return await self.push_messages(
            to=recipient,
            messages=message_payload,
        )

    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        url = self._coerce_https_url(audio.get("url"))
        if url is None:
            url = self._coerce_https_url(audio.get("original_content_url"))
        duration = audio.get("duration")
        if not isinstance(duration, int) or duration <= 0:
            duration = 1000

        if url is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="LINE audio message requires HTTPS URL field.",
            )

        message_payload = [
            {
                "type": "audio",
                "originalContentUrl": url,
                "duration": duration,
            }
        ]
        if isinstance(reply_token, str) and reply_token.strip() != "":
            return await self.reply_messages(
                reply_token=reply_token,
                messages=message_payload,
            )

        return await self.push_messages(
            to=recipient,
            messages=message_payload,
        )

    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        url = self._coerce_https_url(video.get("url"))
        if url is None:
            url = self._coerce_https_url(video.get("original_content_url"))
        preview_url = self._coerce_https_url(video.get("preview_url"))
        if preview_url is None:
            preview_url = self._coerce_https_url(video.get("preview_image_url"))
        if preview_url is None:
            preview_url = url

        if url is None or preview_url is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="LINE video message requires HTTPS URL fields.",
            )

        message_payload = [
            {
                "type": "video",
                "originalContentUrl": url,
                "previewImageUrl": preview_url,
            }
        ]
        if isinstance(reply_token, str) and reply_token.strip() != "":
            return await self.reply_messages(
                reply_token=reply_token,
                messages=message_payload,
            )

        return await self.push_messages(
            to=recipient,
            messages=message_payload,
        )

    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        url = self._coerce_https_url(file.get("url"))
        if url is None:
            url = self._coerce_https_url(file.get("uri"))
        if url is None:
            return self._build_api_response(
                ok=False,
                status=None,
                error="LINE file message requires HTTPS URL field.",
            )

        name = file.get("name")
        if isinstance(name, str) and name.strip() != "":
            text = f"{name.strip()}: {url}"
        else:
            text = url

        return await self.send_text_message(
            recipient=recipient,
            text=text,
            reply_token=reply_token,
        )

    async def send_raw_message(
        self,
        *,
        op: str,
        payload: dict[str, Any],
    ) -> dict | None:
        normalized_op = str(op or "").strip().lower()

        if normalized_op == "reply":
            reply_token = payload.get("reply_token")
            if not isinstance(reply_token, str) or reply_token.strip() == "":
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw reply requires reply_token.",
                )
            messages = payload.get("messages")
            if not isinstance(messages, list):
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw reply requires messages list.",
                )
            return await self.reply_messages(
                reply_token=reply_token,
                messages=messages,
            )

        if normalized_op == "push":
            to = payload.get("to")
            if not isinstance(to, str) or to.strip() == "":
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw push requires recipient.",
                )
            messages = payload.get("messages")
            if not isinstance(messages, list):
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw push requires messages list.",
                )
            return await self.push_messages(
                to=to,
                messages=messages,
            )

        if normalized_op == "multicast":
            to = payload.get("to")
            if not isinstance(to, list):
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw multicast requires recipient list.",
                )
            messages = payload.get("messages")
            if not isinstance(messages, list):
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="LINE raw multicast requires messages list.",
                )
            return await self.multicast_messages(
                to=to,
                messages=messages,
            )

        return self._build_api_response(
            ok=False,
            status=None,
            error=f"Unsupported LINE raw op: {op}",
        )

    def _mime_allowed(self, mime_type: str | None) -> bool:
        if not isinstance(mime_type, str) or mime_type.strip() == "":
            return False

        candidate = mime_type.strip().lower()
        for pattern in self._allowed_mimetypes:
            if fnmatch.fnmatch(candidate, pattern):
                return True

        return False

    async def download_media(
        self,
        *,
        message_id: str,
    ) -> dict[str, Any] | None:
        correlation_id = str(message_id or "").strip()
        if correlation_id == "":
            return None

        if self._client_session is None or self._client_session.closed:
            await self.init()

        url = f"{self._api_base_url}/v2/bot/message/{correlation_id}/content"
        try:
            response = await self._client_session.request(
                method=HTTPMethod.GET.value,
                url=url,
                headers=self._request_headers(),
            )
            try:
                if response.status < 200 or response.status >= 300:
                    self._logging_gateway.error(
                        "LINE media download failed "
                        f"status={response.status} message_id={correlation_id}."
                    )
                    return None

                mime_type = response.headers.get("Content-Type")
                if self._mime_allowed(mime_type) is not True:
                    self._logging_gateway.warning(
                        "LINE media download blocked by mime allow-list "
                        f"mime_type={mime_type!r} message_id={correlation_id}."
                    )
                    return None

                content_length = response.headers.get("Content-Length")
                if content_length not in [None, ""]:
                    try:
                        declared_size = int(content_length)
                    except (TypeError, ValueError):
                        declared_size = None
                    if (
                        isinstance(declared_size, int)
                        and declared_size > self._max_download_bytes
                    ):
                        self._logging_gateway.warning(
                            "LINE media download blocked by size limit "
                            f"declared_bytes={declared_size} "
                            f"limit_bytes={self._max_download_bytes} "
                            f"message_id={correlation_id}."
                        )
                        return None

                suffix = mimetypes.guess_extension(mime_type or "") or ""
                fd, local_path = tempfile.mkstemp(prefix="mugen_line_", suffix=suffix)
                os.close(fd)

                downloaded_bytes = 0
                try:
                    with open(local_path, "wb") as output:
                        async for chunk in response.content.iter_chunked(4096):
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > self._max_download_bytes:
                                raise ValueError("line media exceeds configured size limit")
                            output.write(chunk)
                except Exception:
                    try:
                        os.remove(local_path)
                    except OSError:
                        ...
                    raise

                return {
                    "path": local_path,
                    "mime_type": mime_type,
                }
            finally:
                response.release()
                response.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "LINE media download failed "
                f"message_id={correlation_id} "
                f"error_type={type(exc).__name__} error={exc}"
            )
            return None

    async def get_profile(
        self,
        *,
        user_id: str,
    ) -> dict | None:
        user_id = str(user_id or "").strip()
        if user_id == "":
            return None

        return await self._call_api(
            path=f"/v2/bot/profile/{user_id}",
            method=HTTPMethod.GET,
            correlation_id=user_id,
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

        recipient = str(recipient or "").strip()
        if recipient == "":
            return False

        normalized_state = normalize_processing_state(state)
        if normalized_state != PROCESSING_STATE_START:
            return True

        response = await self._call_api(
            path="/v2/bot/chat/loading/start",
            method=HTTPMethod.POST,
            payload={
                "chatId": recipient,
                "loadingSeconds": 5,
            },
            correlation_id=recipient,
        )

        if isinstance(response, dict) and response.get("ok") is True:
            return True

        self._logging_gateway.warning(
            "LINE processing signal request failed "
            f"recipient={recipient} response={response}."
        )
        return False
