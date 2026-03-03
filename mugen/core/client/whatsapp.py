"""Provides an implementation of IWhatsApp client."""

__all__ = ["DefaultWhatsAppClient", "WhatsAppAPIResponse"]

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from http import HTTPMethod
from io import BytesIO
import json
import mimetypes
import os
import tempfile
import time
from types import SimpleNamespace
from typing import TypedDict
import uuid

import aiohttp

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.logging import ILoggingGateway
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


class WhatsAppAPIResponse(TypedDict):
    """Represents a normalized Graph API response envelope."""

    ok: bool
    status: int | None
    data: dict | None
    error: str | None
    raw: str | None


# pylint: disable=too-many-instance-attributes
class DefaultWhatsAppClient(IWhatsAppClient):
    """An implementation of IWhatsAppClient."""

    _default_http_timeout_seconds: float = 10.0

    _default_max_download_bytes: int = 20 * 1024 * 1024

    _default_max_api_retries: int = 2

    _default_retry_backoff_seconds: float = 0.5

    _default_typing_indicator_enabled: bool = True

    _default_shutdown_timeout_seconds: float = 60.0

    _api_base_path: str

    _api_media_path: str

    _api_messages_path: str

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._client_session: aiohttp.ClientSession = None
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service
        self._http_timeout_seconds = self._resolve_http_timeout_seconds()
        self._max_download_bytes = self._resolve_max_download_bytes()
        self._max_api_retries = self._resolve_max_api_retries()
        self._retry_backoff_seconds = self._resolve_retry_backoff_seconds()
        self._typing_indicator_enabled = self._resolve_typing_indicator_enabled()
        self._shutdown_timeout_seconds = self._resolve_shutdown_timeout_seconds()

        self._api_base_path = (
            f"{self._config.whatsapp.graphapi.base_url}/"
            f"{self._config.whatsapp.graphapi.version}"
        )

        self._api_media_path = f"{self._config.whatsapp.business.phone_number_id}/media"

        self._api_messages_path = (
            f"{self._config.whatsapp.business.phone_number_id}/messages"
        )

    def _resolve_http_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "whatsapp", None), "graphapi", None),
            "timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "whatsapp.graphapi.timeout_seconds",
        )
        if timeout is None:
            return self._default_http_timeout_seconds
        return timeout

    def _resolve_max_download_bytes(self) -> int:
        raw_limit = getattr(
            getattr(getattr(self._config, "whatsapp", None), "graphapi", None),
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
            getattr(getattr(self._config, "whatsapp", None), "graphapi", None),
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
            getattr(getattr(self._config, "whatsapp", None), "graphapi", None),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_backoff,
            field_name="whatsapp.graphapi.retry_backoff_seconds",
            default=self._default_retry_backoff_seconds,
        )

    def _resolve_typing_indicator_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "whatsapp", None), "graphapi", None),
            "typing_indicator_enabled",
            self._default_typing_indicator_enabled,
        )
        return parse_bool_flag(raw_enabled, self._default_typing_indicator_enabled)

    def _resolve_shutdown_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "mugen", None), "runtime", None),
            "shutdown_timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "mugen.runtime.shutdown_timeout_seconds",
        )
        if timeout is None:
            return self._default_shutdown_timeout_seconds
        return timeout

    @staticmethod
    def _format_recipient(recipient: str) -> str:
        return f"+{recipient.lstrip('+')}"

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
    ) -> WhatsAppAPIResponse:
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
        path: str,
        reason: str,
    ) -> None:
        delay_seconds = self._retry_backoff_seconds * (2**attempt)
        self._logging_gateway.warning(
            f"[cid={correlation_id}] Retrying Graph API call for {method} {path} in "
            f"{delay_seconds:.2f}s ({reason}) attempt={attempt + 1}."
        )
        await asyncio.sleep(delay_seconds)

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex

    def _resolve_correlation_id(self, correlation_id: str | None) -> str:
        if isinstance(correlation_id, str) and correlation_id != "":
            return correlation_id
        return self._new_correlation_id()

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.init")
        if (
            self._client_session is not None
            and getattr(self._client_session, "closed", False) is False
        ):
            return

        timeout = aiohttp.ClientTimeout(total=self._http_timeout_seconds)
        self._client_session = aiohttp.ClientSession(timeout=timeout)

    async def verify_startup(self) -> bool:
        correlation_id = self._new_correlation_id()
        phone_number_id = str(self._config.whatsapp.business.phone_number_id)
        probe_response = await self._call_api(
            path=phone_number_id,
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

        status = (
            probe_response.get("status")
            if isinstance(probe_response, dict)
            else None
        )
        error = (
            probe_response.get("error")
            if isinstance(probe_response, dict)
            else "startup probe returned unexpected payload"
        )
        self._logging_gateway.error(
            f"[cid={correlation_id}] WhatsApp startup probe failed "
            f"status={status} error={error!r}."
        )
        return False

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.close")
        if self._client_session is None:
            return

        if getattr(self._client_session, "closed", False) is not True:
            try:
                await asyncio.wait_for(
                    self._client_session.close(),
                    timeout=self._shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError:
                self._logging_gateway.warning(
                    "WhatsApp client session close timed out "
                    f"(timeout_seconds={self._shutdown_timeout_seconds:.2f})."
                )

        self._client_session = None

    async def delete_media(self, media_id: str) -> dict | None:
        return await self._call_api(
            media_id,
            method=HTTPMethod.DELETE,
            correlation_id=media_id,
        )

    async def download_media(self, media_url: str, mimetype: str) -> str | None:
        return await self._download_file_http(
            media_url,
            mimetype,
            correlation_id=media_url,
        )

    async def retrieve_media_url(self, media_id: str) -> dict | None:
        return await self._call_api(
            media_id,
            method=HTTPMethod.GET,
            correlation_id=media_id,
        )

    async def send_audio_message(
        self,
        audio: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "audio",
            "audio": audio,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_contacts_message(
        self,
        contacts: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "contacts",
            "contacts": contacts,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_document_message(
        self,
        document: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "document",
            "document": document,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_image_message(
        self,
        image: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "image",
            "image": image,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_interactive_message(
        self,
        interactive: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "interactive",
            "interactive": interactive,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_location_message(
        self,
        location: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "location",
            "location": location,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_reaction_message(
        self, reaction: dict, recipient: str
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "reaction",
            "reaction": reaction,
        }

        return await self._send_message(data=data)

    async def send_sticker_message(
        self,
        sticker: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "sticker",
            "sticker": sticker,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_template_message(
        self,
        template: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "template",
            "template": template,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_text_message(
        self,
        message: str,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message,
            },
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_video_message(
        self,
        video: dict,
        recipient: str,
        reply_to: str = None,
    ) -> dict | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "type": "video",
            "video": video,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        if not self._typing_indicator_enabled:
            return None

        try:
            normalized_state = normalize_processing_state(state)
        except ValueError as exc:
            self._logging_gateway.warning(str(exc))
            return False

        if normalized_state == PROCESSING_STATE_STOP:
            return True

        if not isinstance(recipient, str) or recipient.strip() == "":
            self._logging_gateway.warning(
                "Cannot emit WhatsApp thinking signal without a recipient."
            )
            return False

        if not isinstance(message_id, str) or message_id.strip() == "":
            self._logging_gateway.warning(
                "Cannot emit WhatsApp thinking start signal without message_id."
            )
            return False

        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._format_recipient(recipient),
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {
                "type": "text",
            },
        }

        try:
            response = await self._call_api(
                path=self._api_messages_path,
                content_type="application/json",
                data=data,
                correlation_id=message_id,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Failed to emit WhatsApp thinking signal "
                f"(recipient={recipient} state={normalized_state}): {exc}"
            )
            return False

        ok = isinstance(response, dict) and response.get("ok") is True
        if not ok:
            self._logging_gateway.warning(
                "WhatsApp thinking signal did not succeed "
                f"(recipient={recipient} state={normalized_state})."
            )
            return False

        return True

    async def upload_media(
        self,
        file_path: str | BytesIO,
        file_type: str,
    ) -> dict | None:
        if isinstance(file_path, BytesIO):
            payload = file_path.getvalue()

            def files_factory() -> tuple[aiohttp.FormData, list]:
                files = aiohttp.FormData()
                files.add_field("messaging_product", "whatsapp")
                files.add_field("type", file_type)
                files.add_field(
                    "file",
                    payload,
                    filename="upload.bin",
                    content_type=file_type,
                )
                return files, []

            return await self._call_api(
                self._api_media_path,
                files_factory=files_factory,
                correlation_id=self._new_correlation_id(),
            )

        try:
            with open(file_path, "rb"):
                pass
        except OSError as e:
            self._logging_gateway.error(str(e))
            return self._build_api_response(ok=False, status=None, error=str(e))

        file_name = os.path.basename(file_path)

        def files_factory() -> tuple[aiohttp.FormData, list]:
            files = aiohttp.FormData()
            files.add_field("messaging_product", "whatsapp")
            files.add_field("type", file_type)
            file_stream = open(file_path, "rb")
            files.add_field(
                "file",
                file_stream,
                filename=file_name,
                content_type=file_type,
            )
            return files, [file_stream]

        return await self._call_api(
            self._api_media_path,
            files_factory=files_factory,
            correlation_id=file_name,
        )

    async def _call_api(
        self,
        path: str,
        content_type: str = None,
        data: dict = None,
        files: dict = None,
        files_factory: Callable[[], tuple[aiohttp.FormData, list]] | None = None,
        method: str = HTTPMethod.POST,
        correlation_id: str | None = None,
    ) -> dict | None:
        """Make a call to Graph API."""
        resolved_correlation_id = self._resolve_correlation_id(correlation_id)
        if self._client_session is None or (
            getattr(self._client_session, "closed", False) is True
        ):
            error = "WhatsApp client session is not initialized."
            self._logging_gateway.error(error)
            return self._build_api_response(ok=False, status=None, error=error)

        headers = {
            "Authorization": f"Bearer {self._config.whatsapp.graphapi.access_token}",
        }

        if content_type:
            headers["Content-Type"] = content_type

        url = f"{self._api_base_path}/{path}"

        for attempt in range(self._max_api_retries + 1):
            started = time.perf_counter()
            kwargs = {
                "headers": headers,
            }
            if data is not None:
                kwargs["data"] = json.dumps(data)

            resources_to_close: list = []
            if files_factory is not None:
                try:
                    built_files, resources_to_close = files_factory()
                except OSError as e:
                    error = str(e)
                    self._logging_gateway.error(error)
                    return self._build_api_response(ok=False, status=None, error=error)
                kwargs["data"] = built_files
            elif files is not None:
                kwargs["data"] = files

            try:
                match method:
                    case HTTPMethod.DELETE:
                        response = await self._client_session.delete(url, **kwargs)
                    case HTTPMethod.GET:
                        response = await self._client_session.get(url, **kwargs)
                    case HTTPMethod.POST:
                        response = await self._client_session.post(url, **kwargs)
                    case HTTPMethod.PUT:
                        response = await self._client_session.put(url, **kwargs)
                    case _:
                        raise ValueError(f"Unsupported HTTP method: {method}")

                response_text = await response.text()
                response_data = self._parse_response_payload(response_text)
                latency_ms = (time.perf_counter() - started) * 1000

                if response.status >= 200 and response.status < 300:
                    self._logging_gateway.debug(
                        f"[cid={resolved_correlation_id}] Graph API success "
                        f"{method} {path} status={response.status} "
                        f"latency_ms={latency_ms:.2f} attempt={attempt + 1}."
                    )
                    return self._build_api_response(
                        ok=True,
                        status=response.status,
                        data=response_data,
                        raw=response_text,
                    )

                error = (
                    f"Graph API call failed ({response.status}) for {method} {path}."
                )
                if (
                    self._is_retryable_status(response.status)
                    and attempt < self._max_api_retries
                ):
                    self._logging_gateway.warning(
                        f"[cid={resolved_correlation_id}] Graph API retryable status "
                        f"for {method} {path} status={response.status} "
                        f"latency_ms={latency_ms:.2f} attempt={attempt + 1}."
                    )
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=resolved_correlation_id,
                        method=str(method),
                        path=path,
                        reason=f"status={response.status}",
                    )
                    continue

                self._logging_gateway.debug(
                    f"[cid={resolved_correlation_id}] Graph API terminal failure "
                    f"{method} {path} status={response.status} "
                    f"latency_ms={latency_ms:.2f} attempt={attempt + 1}."
                )
                self._logging_gateway.error(error)
                if response_text != "":
                    self._logging_gateway.error(response_text)
                return self._build_api_response(
                    ok=False,
                    status=response.status,
                    data=response_data,
                    error=error,
                    raw=response_text,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < self._max_api_retries:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=resolved_correlation_id,
                        method=str(method),
                        path=path,
                        reason=str(e),
                    )
                    continue

                error = str(e)
                latency_ms = (time.perf_counter() - started) * 1000
                self._logging_gateway.debug(
                    f"[cid={resolved_correlation_id}] Graph API transport failure "
                    f"{method} {path} latency_ms={latency_ms:.2f} "
                    f"attempt={attempt + 1}."
                )
                self._logging_gateway.error(error)
                return self._build_api_response(ok=False, status=None, error=error)
            finally:
                for resource in resources_to_close:
                    resource.close()

        return self._build_api_response(
            ok=False, status=None, error="Unknown API failure."
        )

    async def _download_file_http(
        self,
        url: str,
        mimetype: str,
        correlation_id: str | None = None,
    ) -> str | None:
        resolved_correlation_id = self._resolve_correlation_id(correlation_id)
        if self._client_session is None or (
            getattr(self._client_session, "closed", False) is True
        ):
            self._logging_gateway.error("WhatsApp client session is not initialized.")
            return None

        headers = {
            "Authorization": f"Bearer {self._config.whatsapp.graphapi.access_token}",
        }

        kwargs = {
            "headers": headers,
        }

        file_path: str | None = None
        download_complete = False
        started = time.perf_counter()
        try:
            async with self._managed_http_get(url, **kwargs) as response:
                if response.status != 200:
                    self._logging_gateway.error(
                        f"Media download failed with status code {response.status}."
                    )
                    return None

                extension = self._resolve_media_extension(
                    declared_mimetype=mimetype,
                    response=response,
                )
                if not extension:
                    self._logging_gateway.error(
                        "Media download failed due to missing or unsupported mimetype."
                    )
                    return None

                fd, file_path = tempfile.mkstemp(suffix=extension)
                os.close(fd)
                bytes_written = 0
                with open(file_path, "wb") as file:
                    if hasattr(response, "content") and hasattr(
                        response.content, "iter_chunked"
                    ):
                        async for chunk in response.content.iter_chunked(8192):
                            bytes_written += len(chunk)
                            if bytes_written > self._max_download_bytes:
                                self._logging_gateway.error(
                                    "Downloaded media exceeded max allowed size."
                                )
                                return None
                            file.write(chunk)
                    else:
                        body = await response.read()
                        bytes_written = len(body)
                        if bytes_written > self._max_download_bytes:
                            self._logging_gateway.error(
                                "Downloaded media exceeded max allowed size."
                            )
                            return None
                        file.write(body)
            download_complete = True
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"[cid={resolved_correlation_id}] WhatsApp media download success "
                f"latency_ms={latency_ms:.2f} bytes={bytes_written}."
            )
            return file_path
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"[cid={resolved_correlation_id}] WhatsApp media download failed "
                f"latency_ms={latency_ms:.2f}."
            )
            self._logging_gateway.error(str(e))
            return None
        finally:
            if not download_complete and file_path and os.path.exists(file_path):
                os.remove(file_path)

    @staticmethod
    def _normalize_mimetype(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.split(";", 1)[0].strip().lower()
        if normalized == "":
            return None
        return normalized

    def _resolve_media_extension(
        self,
        *,
        declared_mimetype: object,
        response: object,
    ) -> str | None:
        normalized_mimetype = self._normalize_mimetype(declared_mimetype)
        if normalized_mimetype is None:
            headers = getattr(response, "headers", None)
            header_value = None
            if hasattr(headers, "get") and callable(headers.get):
                header_value = headers.get("Content-Type")
                if header_value in [None, ""]:
                    header_value = headers.get("content-type")
            normalized_mimetype = self._normalize_mimetype(header_value)

        if normalized_mimetype is None:
            return None

        return mimetypes.guess_extension(normalized_mimetype)

    @asynccontextmanager
    async def _managed_http_get(self, url: str, **kwargs):
        response = await self._client_session.get(url, **kwargs)
        try:
            yield response
        finally:
            release = getattr(response, "release", None)
            if callable(release):
                release()
            close = getattr(response, "close", None)
            if callable(close):
                close()

    async def _send_message(self, data: dict) -> dict | None:
        """Utility for all message functions."""
        correlation_id = None
        context = data.get("context")
        if isinstance(context, dict):
            context_message_id = context.get("message_id")
            if isinstance(context_message_id, str) and context_message_id != "":
                correlation_id = context_message_id

        if correlation_id is None and isinstance(data.get("reaction"), dict):
            reaction_message_id = data["reaction"].get("message_id")
            if isinstance(reaction_message_id, str) and reaction_message_id != "":
                correlation_id = reaction_message_id

        return await self._call_api(
            path=self._api_messages_path,
            content_type="application/json",
            data=data,
            correlation_id=correlation_id,
        )
