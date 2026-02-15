"""Provides an implementation of IWhatsApp client."""

__all__ = ["DefaultWhatsAppClient", "WhatsAppAPIResponse"]

import asyncio
from http import HTTPMethod
from io import BytesIO
import json
import mimetypes
import os
import tempfile
from types import SimpleNamespace
from typing import TypedDict

import aiohttp

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


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
            self._default_http_timeout_seconds,
        )
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = self._default_http_timeout_seconds

        if timeout <= 0:
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
            self._default_retry_backoff_seconds,
        )
        try:
            backoff = float(raw_backoff)
        except (TypeError, ValueError):
            backoff = self._default_retry_backoff_seconds

        if backoff <= 0:
            return self._default_retry_backoff_seconds

        return backoff

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
        method: str,
        path: str,
        reason: str,
    ) -> None:
        delay_seconds = self._retry_backoff_seconds * (2**attempt)
        self._logging_gateway.warning(
            f"Retrying Graph API call for {method} {path} in "
            f"{delay_seconds:.2f}s ({reason})."
        )
        await asyncio.sleep(delay_seconds)

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.init")
        if (
            self._client_session is not None
            and getattr(self._client_session, "closed", False) is False
        ):
            return

        timeout = aiohttp.ClientTimeout(total=self._http_timeout_seconds)
        self._client_session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.close")
        if self._client_session is None:
            return

        if getattr(self._client_session, "closed", False) is not True:
            await self._client_session.close()

        self._client_session = None

    async def delete_media(self, media_id: str) -> dict | None:
        return await self._call_api(media_id, method=HTTPMethod.DELETE)

    async def download_media(self, media_url: str, mimetype: str) -> str | None:
        return await self._download_file_http(media_url, mimetype)

    async def retrieve_media_url(self, media_id: str) -> dict | None:
        return await self._call_api(media_id, method=HTTPMethod.GET)

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

    async def upload_media(
        self,
        file_path: str | BytesIO,
        file_type: str,
    ) -> dict | None:
        files = aiohttp.FormData()
        files.add_field("messaging_product", "whatsapp")
        files.add_field("type", file_type)

        if isinstance(file_path, BytesIO):
            files.add_field(
                "file",
                file_path.getvalue(),
                filename="upload.bin",
                content_type=file_type,
            )
            return await self._call_api(self._api_media_path, files=files)

        try:
            with open(file_path, "rb") as file:
                payload = file.read()
        except OSError as e:
            self._logging_gateway.error(str(e))
            return self._build_api_response(ok=False, status=None, error=str(e))

        files.add_field(
            "file",
            payload,
            filename=os.path.basename(file_path),
            content_type=file_type,
        )
        return await self._call_api(self._api_media_path, files=files)

    async def _call_api(
        self,
        path: str,
        content_type: str = None,
        data: dict = None,
        files: dict = None,
        method: str = HTTPMethod.POST,
    ) -> dict | None:
        """Make a call to Graph API."""
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

        kwargs = {
            "headers": headers,
        }

        if data is not None:
            kwargs["data"] = json.dumps(data)

        if files is not None:
            kwargs["data"] = files

        for attempt in range(self._max_api_retries + 1):
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

                if response.status >= 200 and response.status < 300:
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
                    await self._wait_before_retry(
                        attempt=attempt,
                        method=str(method),
                        path=path,
                        reason=f"status={response.status}",
                    )
                    continue

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
                        method=str(method),
                        path=path,
                        reason=str(e),
                    )
                    continue

                error = str(e)
                self._logging_gateway.error(error)
                return self._build_api_response(ok=False, status=None, error=error)

        return self._build_api_response(
            ok=False, status=None, error="Unknown API failure."
        )

    async def _download_file_http(self, url: str, mimetype: str) -> str | None:
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
        try:
            response = await self._client_session.get(url, **kwargs)
            if response.status != 200:
                self._logging_gateway.error(
                    f"Media download failed with status code {response.status}."
                )
                return None

            extension = mimetypes.guess_extension(mimetype.split(";")[0].strip())
            if not extension:
                return None

            bytes_written = 0
            body = b""
            if hasattr(response, "content") and hasattr(
                response.content, "iter_chunked"
            ):
                stream = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    bytes_written += len(chunk)
                    if bytes_written > self._max_download_bytes:
                        self._logging_gateway.error(
                            "Downloaded media exceeded max allowed size."
                        )
                        return None
                    stream.extend(chunk)
                body = bytes(stream)
            else:
                body = await response.read()
                bytes_written = len(body)
                if bytes_written > self._max_download_bytes:
                    self._logging_gateway.error(
                        "Downloaded media exceeded max allowed size."
                    )
                    return None

            fd, file_path = tempfile.mkstemp(suffix=extension)
            os.close(fd)
            with open(file_path, "wb") as file:
                file.write(body)
            download_complete = True
            return file_path
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            self._logging_gateway.error(str(e))
            return None
        finally:
            if not download_complete and file_path and os.path.exists(file_path):
                os.remove(file_path)

    async def _send_message(self, data: dict) -> dict | None:
        """Utility for all message functions."""
        return await self._call_api(
            path=self._api_messages_path,
            content_type="application/json",
            data=data,
        )
