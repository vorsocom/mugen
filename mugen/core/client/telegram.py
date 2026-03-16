"""Provides an implementation of ITelegramClient."""

__all__ = ["DefaultTelegramClient", "MultiProfileTelegramClient", "TelegramAPIResponse"]

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

from mugen.core.client.runtime_profile_manager import SimpleProfileClientManager
from mugen.core.contract.client.telegram import ITelegramClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import (
    IRelationalStorageGateway,
)
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


class TelegramAPIResponse(TypedDict):
    """Represents a normalized Telegram Bot API response envelope."""

    ok: bool
    status: int | None
    data: dict | None
    error: str | None
    raw: str | None


# pylint: disable=too-many-instance-attributes
class DefaultTelegramClient(ITelegramClient):
    """An implementation of ITelegramClient."""

    _default_api_base_url: str = "https://api.telegram.org"

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

        self._api_base_url = self._resolve_api_base_url()
        self._http_timeout_seconds = self._resolve_http_timeout_seconds()
        self._max_download_bytes = self._resolve_max_download_bytes()
        self._max_api_retries = self._resolve_max_api_retries()
        self._retry_backoff_seconds = self._resolve_retry_backoff_seconds()
        self._typing_enabled = self._resolve_typing_enabled()
        self._allowed_mimetypes = self._resolve_allowed_mimetypes()
        self._shutdown_timeout_seconds = self._resolve_shutdown_timeout_seconds()

        bot_token = str(self._config.telegram.bot.token or "").strip()
        self._api_base_path = f"{self._api_base_url}/bot{bot_token}"
        self._file_base_path = f"{self._api_base_url}/file/bot{bot_token}"

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex

    def _resolve_api_base_url(self) -> str:
        raw_base_url = getattr(
            getattr(getattr(self._config, "telegram", None), "api", None),
            "base_url",
            self._default_api_base_url,
        )
        if not isinstance(raw_base_url, str) or raw_base_url.strip() == "":
            return self._default_api_base_url
        return raw_base_url.strip().rstrip("/")

    def _resolve_http_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "telegram", None), "api", None),
            "timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "telegram.api.timeout_seconds",
        )
        if timeout is None:
            return self._default_http_timeout_seconds
        return timeout

    def _resolve_max_download_bytes(self) -> int:
        raw_limit = getattr(
            getattr(getattr(self._config, "telegram", None), "media", None),
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
            getattr(getattr(self._config, "telegram", None), "api", None),
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
            getattr(getattr(self._config, "telegram", None), "api", None),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_backoff,
            field_name="telegram.api.retry_backoff_seconds",
            default=self._default_retry_backoff_seconds,
        )

    def _resolve_typing_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "telegram", None), "typing", None),
            "enabled",
            self._default_typing_enabled,
        )
        return parse_bool_flag(raw_enabled, self._default_typing_enabled)

    def _resolve_allowed_mimetypes(self) -> tuple[str, ...]:
        raw_allowed = getattr(
            getattr(getattr(self._config, "telegram", None), "media", None),
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
    def _parse_response_payload(response_text: str | None) -> dict | None:
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
        data: dict | None = None,
        error: str | None = None,
        raw: str | None = None,
    ) -> TelegramAPIResponse:
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

    async def _wait_before_retry(
        self,
        *,
        attempt: int,
        correlation_id: str,
        method: str,
        endpoint: str,
        reason: str,
    ) -> None:
        delay_seconds = self._retry_backoff_seconds * (2**attempt)
        self._logging_gateway.warning(
            f"[cid={correlation_id}] Retrying Telegram API call for {method} {endpoint} in "
            f"{delay_seconds:.2f}s ({reason}) attempt={attempt + 1}."
        )
        await asyncio.sleep(delay_seconds)

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultTelegramClient.init")
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
            "getMe",
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
            f"[cid={correlation_id}] Telegram startup probe failed "
            f"status={status} error={error!r}."
        )
        return False

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultTelegramClient.close")
        if self._client_session is None:
            return

        if getattr(self._client_session, "closed", False) is not True:
            try:
                await asyncio.wait_for(
                    self._client_session.close(),
                    timeout=self._shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError:
                message = (
                    "Telegram client session close timed out "
                    f"(timeout_seconds={self._shutdown_timeout_seconds:.2f})."
                )
                self._logging_gateway.error(message)
                raise RuntimeError(message)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                message = (
                    "Telegram client session close failed "
                    f"error_type={type(exc).__name__} error={exc}"
                )
                self._logging_gateway.error(message)
                raise RuntimeError(message) from exc

        self._client_session = None

    async def _call_api(
        self,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        method: HTTPMethod = HTTPMethod.POST,
        correlation_id: str | None = None,
    ) -> TelegramAPIResponse:
        cid = correlation_id if isinstance(correlation_id, str) else self._new_correlation_id()
        if self._client_session is None or self._client_session.closed:
            await self.init()

        url = f"{self._api_base_path}/{endpoint}"
        for attempt in range(self._max_api_retries + 1):
            try:
                if method == HTTPMethod.GET:
                    response = await self._client_session.get(url, params=payload)
                else:
                    response = await self._client_session.post(url, json=payload)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if attempt < self._max_api_retries:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=cid,
                        method=str(method),
                        endpoint=endpoint,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error=f"Telegram API request error: {type(exc).__name__}: {exc}",
                )

            status = response.status
            response_text = await response.text()
            payload_dict = self._parse_response_payload(response_text)
            if (
                200 <= status < 300
                and isinstance(payload_dict, dict)
                and payload_dict.get("ok") is True
            ):
                return self._build_api_response(
                    ok=True,
                    status=status,
                    data=payload_dict,
                    raw=response_text,
                )

            error_message = None
            if isinstance(payload_dict, dict):
                description = payload_dict.get("description")
                if isinstance(description, str) and description.strip() != "":
                    error_message = description.strip()
            if error_message is None:
                error_message = (
                    f"Telegram API call failed for {endpoint} with status {status}."
                )

            if self._is_retryable_status(status) and attempt < self._max_api_retries:
                await self._wait_before_retry(
                    attempt=attempt,
                    correlation_id=cid,
                    method=str(method),
                    endpoint=endpoint,
                    reason=error_message,
                )
                continue

            return self._build_api_response(
                ok=False,
                status=status,
                data=payload_dict if isinstance(payload_dict, dict) else None,
                error=error_message,
                raw=response_text,
            )

        return self._build_api_response(
            ok=False,
            status=None,
            error=f"Telegram API call exhausted retries for endpoint: {endpoint}.",
        )

    async def _call_api_with_file(
        self,
        endpoint: str,
        *,
        file_field: str,
        file_path: str,
        payload_fields: dict[str, Any],
        correlation_id: str | None = None,
    ) -> TelegramAPIResponse:
        cid = correlation_id if isinstance(correlation_id, str) else self._new_correlation_id()
        if self._client_session is None or self._client_session.closed:
            await self.init()

        if not isinstance(file_path, str) or file_path.strip() == "":
            return self._build_api_response(
                ok=False,
                status=None,
                error=f"Invalid media path for endpoint: {endpoint}.",
            )

        normalized_path = file_path.strip()
        if os.path.isfile(normalized_path) is not True:
            return self._build_api_response(
                ok=False,
                status=None,
                error=f"Media file not found for endpoint: {endpoint}.",
            )

        url = f"{self._api_base_path}/{endpoint}"
        for attempt in range(self._max_api_retries + 1):
            try:
                with open(normalized_path, "rb") as handle:
                    form = aiohttp.FormData()
                    for key, value in payload_fields.items():
                        if value is None:
                            continue
                        if isinstance(value, bool):
                            form.add_field(key, "true" if value else "false")
                        else:
                            form.add_field(key, str(value))
                    form.add_field(
                        file_field,
                        handle,
                        filename=os.path.basename(normalized_path),
                    )
                    response = await self._client_session.post(url, data=form)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if attempt < self._max_api_retries:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=cid,
                        method=str(HTTPMethod.POST),
                        endpoint=endpoint,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error=f"Telegram API request error: {type(exc).__name__}: {exc}",
                )

            status = response.status
            response_text = await response.text()
            payload_dict = self._parse_response_payload(response_text)
            if (
                200 <= status < 300
                and isinstance(payload_dict, dict)
                and payload_dict.get("ok") is True
            ):
                return self._build_api_response(
                    ok=True,
                    status=status,
                    data=payload_dict,
                    raw=response_text,
                )

            error_message = None
            if isinstance(payload_dict, dict):
                description = payload_dict.get("description")
                if isinstance(description, str) and description.strip() != "":
                    error_message = description.strip()
            if error_message is None:
                error_message = (
                    f"Telegram API call failed for {endpoint} with status {status}."
                )

            if self._is_retryable_status(status) and attempt < self._max_api_retries:
                await self._wait_before_retry(
                    attempt=attempt,
                    correlation_id=cid,
                    method=str(HTTPMethod.POST),
                    endpoint=endpoint,
                    reason=error_message,
                )
                continue

            return self._build_api_response(
                ok=False,
                status=status,
                data=payload_dict if isinstance(payload_dict, dict) else None,
                error=error_message,
                raw=response_text,
            )

        return self._build_api_response(
            ok=False,
            status=None,
            error=f"Telegram API call exhausted retries for endpoint: {endpoint}.",
        )

    @staticmethod
    def _resolve_media_source(
        media: dict[str, Any],
    ) -> tuple[str, str]:
        media_id = media.get("id")
        if isinstance(media_id, str) and media_id.strip() != "":
            return ("remote", media_id.strip())

        file_id = media.get("file_id")
        if isinstance(file_id, str) and file_id.strip() != "":
            return ("remote", file_id.strip())

        uri = media.get("uri")
        if isinstance(uri, str) and uri.strip() != "":
            return ("local", uri.strip())

        path = media.get("path")
        if isinstance(path, str) and path.strip() != "":
            return ("local", path.strip())

        raise ValueError("Media payload must include id/file_id or uri/path.")

    async def _send_media_message(
        self,
        *,
        endpoint: str,
        field_name: str,
        media: dict[str, Any],
        chat_id: str,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        source_kind, source_value = self._resolve_media_source(media)
        caption = media.get("caption")

        payload_fields: dict[str, Any] = {
            "chat_id": str(chat_id),
            "reply_to_message_id": reply_to_message_id,
            "caption": caption if isinstance(caption, str) else None,
        }

        if source_kind == "remote":
            payload = {
                **payload_fields,
                field_name: source_value,
            }
            return await self._call_api(endpoint, payload=payload)

        return await self._call_api_with_file(
            endpoint,
            file_field=field_name,
            file_path=source_value,
            payload_fields=payload_fields,
        )

    async def send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "text": text,
        }
        if isinstance(reply_markup, dict):
            payload["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self._call_api("sendMessage", payload=payload)

    async def send_audio_message(
        self,
        *,
        chat_id: str,
        audio: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        return await self._send_media_message(
            endpoint="sendAudio",
            field_name="audio",
            media=audio,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_file_message(
        self,
        *,
        chat_id: str,
        document: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        return await self._send_media_message(
            endpoint="sendDocument",
            field_name="document",
            media=document,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_image_message(
        self,
        *,
        chat_id: str,
        photo: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        return await self._send_media_message(
            endpoint="sendPhoto",
            field_name="photo",
            media=photo,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_video_message(
        self,
        *,
        chat_id: str,
        video: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        return await self._send_media_message(
            endpoint="sendVideo",
            field_name="video",
            media=video,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
    ) -> dict | None:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
        }
        if isinstance(text, str):
            payload["text"] = text
        if isinstance(show_alert, bool):
            payload["show_alert"] = show_alert
        return await self._call_api("answerCallbackQuery", payload=payload)

    async def emit_processing_signal(
        self,
        chat_id: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = message_id
        if self._typing_enabled is not True:
            return True

        normalized_state = normalize_processing_state(state)
        if normalized_state != PROCESSING_STATE_START:
            return True

        response = await self._call_api(
            "sendChatAction",
            payload={
                "chat_id": str(chat_id),
                "action": "typing",
            },
        )
        return bool(response.get("ok"))

    def _mime_allowed(self, content_type: str) -> bool:
        normalized = str(content_type or "").strip().lower()
        if normalized == "":
            return False
        return any(fnmatch.fnmatch(normalized, pattern) for pattern in self._allowed_mimetypes)

    def _extract_result(self, payload: dict | None, context: str) -> dict | None:
        if payload is None:
            self._logging_gateway.error(f"Missing payload for {context}.")
            return None

        if not isinstance(payload, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        if payload.get("ok") is not True:
            self._logging_gateway.error(f"{context} failed.")
            error = payload.get("error")
            if error not in [None, ""]:
                self._logging_gateway.error(str(error))
            raw = payload.get("raw")
            if isinstance(raw, str) and raw != "":
                self._logging_gateway.error(raw)
            return None

        data = payload.get("data")
        if data is None:
            return {}

        if not isinstance(data, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        result = data.get("result")
        if result is None:
            return {}

        if not isinstance(result, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        return result

    async def download_media(self, file_id: str) -> dict[str, Any] | None:
        if not isinstance(file_id, str) or file_id.strip() == "":
            self._logging_gateway.error("Telegram media file id is invalid.")
            return None

        get_file_response = await self._call_api(
            "getFile",
            payload={"file_id": file_id.strip()},
        )
        file_data = self._extract_result(get_file_response, "file lookup")
        if file_data is None:
            return None

        file_path = file_data.get("file_path")
        if not isinstance(file_path, str) or file_path.strip() == "":
            self._logging_gateway.error("Telegram media lookup missing file_path.")
            return None

        reported_size = file_data.get("file_size")
        if isinstance(reported_size, int) and reported_size > self._max_download_bytes:
            self._logging_gateway.error(
                "Telegram media exceeds configured max download bytes "
                f"(file_size={reported_size} max={self._max_download_bytes})."
            )
            return None

        if self._client_session is None or self._client_session.closed:
            await self.init()

        download_url = f"{self._file_base_path}/{file_path.lstrip('/')}"
        try:
            response = await self._client_session.get(download_url)
            status = response.status
            if status < 200 or status >= 300:
                self._logging_gateway.error(
                    "Telegram media download failed "
                    f"status={status} file_id={file_id}."
                )
                return None

            blob = await response.read()
            if len(blob) > self._max_download_bytes:
                self._logging_gateway.error(
                    "Telegram media exceeds configured max download bytes "
                    f"(file_size={len(blob)} max={self._max_download_bytes})."
                )
                return None

            content_type = str(response.headers.get("Content-Type", "") or "")
            content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
            if content_type == "":
                guessed_type, _ = mimetypes.guess_type(file_path)
                content_type = (guessed_type or "application/octet-stream").lower()

            if self._mime_allowed(content_type) is not True:
                self._logging_gateway.error(
                    "Telegram media mime type is not allowed "
                    f"(mime_type={content_type!r})."
                )
                return None

            suffix = os.path.splitext(file_path)[1]
            fd, local_path = tempfile.mkstemp(prefix="mugen_telegram_", suffix=suffix)
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)

            return {
                "path": local_path,
                "mime_type": content_type,
                "size": len(blob),
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Telegram media download failed "
                f"error_type={type(exc).__name__} error={exc}"
            )
            return None


class MultiProfileTelegramClient(SimpleProfileClientManager, ITelegramClient):
    """Telegram client manager that multiplexes configured runtime profiles."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        super().__init__(
            platform="telegram",
            client_cls=DefaultTelegramClient,
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            relational_storage_gateway=relational_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

    async def send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().send_text_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_audio_message(
        self,
        *,
        chat_id: str,
        audio: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().send_audio_message(
            chat_id=chat_id,
            audio=audio,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_file_message(
        self,
        *,
        chat_id: str,
        document: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().send_file_message(
            chat_id=chat_id,
            document=document,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_image_message(
        self,
        *,
        chat_id: str,
        photo: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().send_image_message(
            chat_id=chat_id,
            photo=photo,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_video_message(
        self,
        *,
        chat_id: str,
        video: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().send_video_message(
            chat_id=chat_id,
            video=video,
            reply_to_message_id=reply_to_message_id,
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
    ) -> dict | None:
        await self.init()
        return await self._client_for().answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )

    async def emit_processing_signal(
        self,
        chat_id: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        await self.init()
        return await self._client_for().emit_processing_signal(
            chat_id,
            state=state,
            message_id=message_id,
        )

    async def download_media(self, file_id: str) -> dict[str, Any] | None:
        await self.init()
        return await self._client_for().download_media(file_id)
