"""Provides an implementation of IWhatsApp client."""

__all__ = ["DefaultWhatsAppClient"]

import asyncio
from http import HTTPMethod
from io import BytesIO
import json
from types import SimpleNamespace

import aiohttp

from mugen.core.contract.ipc_service import IIPCService
from mugen.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from mugen.core.contract.logging_gateway import ILoggingGateway
from mugen.core.contract.messaging_service import IMessagingService
from mugen.core.contract.user_service import IUserService
from mugen.core.contract.whatsapp_client import IWhatsAppClient


# pylint: disable=too-many-instance-attributes
class DefaultWhatsAppClient(IWhatsAppClient):
    """An implementation of IWhatsAppClient."""

    _api_base_path: str

    _api_media_path: str

    _api_messages_path: str

    _stop_listening: bool = False

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: dict = None,
        ipc_queue: asyncio.Queue = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._client_session: aiohttp.ClientSession = None
        self._config = SimpleNamespace(**config)
        self._ipc_queue = ipc_queue
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        self._api_base_path = (
            f"{self._config.whatsapp_graph_api_base_url}/"
            f"{self._config.whatsapp_graph_api_version}"
        )

        self._api_media_path = f"{self._config.whatsapp_business_phone_number_id}/media"

        self._api_messages_path = (
            f"{self._config.whatsapp_business_phone_number_id}/messages"
        )

    async def __aenter__(self) -> None:
        """Initialisation."""
        self._logging_gateway.debug("DefaultWhatsAppClient.__aenter__")
        self._client_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Finalisation."""
        self._logging_gateway.debug("DefaultWhatsAppClient.__aexit__")
        self._stop_listening = True
        await self._client_session.close()
        await asyncio.sleep(0.250)

    async def listen_forever(self, loop_sleep_time: float = 0.01) -> None:
        # Loop until exit.
        while not self._stop_listening:
            try:
                while not self._ipc_queue.empty():
                    payload = await self._ipc_queue.get()
                    asyncio.create_task(
                        self._ipc_service.handle_ipc_request("whatsapp", payload)
                    )
                    self._ipc_queue.task_done()

                await asyncio.sleep(loop_sleep_time)
            except asyncio.exceptions.CancelledError:
                self._logging_gateway.debug("WhatsApp listen_forever loop exited.")
                break

    async def delete_media(self, media_id: str) -> str | None:
        return await self._call_api(media_id, method=HTTPMethod.DELETE)

    async def download_media(self, media_url: str) -> str | None:
        return await self._call_api(media_url, method=HTTPMethod.GET)

    async def retrieve_media_url(self, media_id: str) -> str | None:
        return await self._call_api(media_id, method=HTTPMethod.GET)

    async def send_audio_message(
        self,
        audio: dict,
        recipient: str,
        reply_to: str = None,
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
            "type": "location",
            "location": location,
        }

        if reply_to:
            data["context"] = {
                "message_id": reply_to,
            }

        return await self._send_message(data=data)

    async def send_reaction_message(self, reaction: dict, recipient: str) -> None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
            "type": "reaction",
            "reaction": reaction,
        }

        return await self._send_message(data=data)

    async def send_sticker_message(
        self,
        sticker: dict,
        recipient: str,
        reply_to: str = None,
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{recipient}",
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
    ) -> str | None:
        files = aiohttp.FormData()
        files.add_field("messaging_product", "whatsapp")
        files.add_field("type", file_type)

        if isinstance(file_path, BytesIO):
            files.add_field("file", file_path.getvalue(), content_type=file_type)
            return await self._call_api(self._api_media_path, files=files)

        with open(file_path, "rb") as file:
            files.add_field("file", file)
            return await self._call_api(self._api_media_path, files=files)

    async def _call_api(
        self,
        path: str,
        content_type: str = None,
        data: dict = None,
        files: dict = None,
        method: str = HTTPMethod.POST,
    ) -> str | None:
        """Make a call to Graph API."""
        headers = {
            "Authorization": f"Bearer {self._config.whatsapp_graph_api_access_token}",
        }

        if content_type:
            headers["Content-type"] = content_type

        url = f"{self._api_base_path}/{path}"

        kwargs = {
            "headers": headers,
        }

        if data:
            kwargs["data"] = json.dumps(data)

        if files:
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
                    pass

            return await response.text()
        except aiohttp.ClientConnectionError as e:
            self._logging_gateway.error(str(e))

    async def _send_message(self, data: dict) -> str | None:
        """Utility for all message functions."""
        return await self._call_api(
            path=self._api_messages_path,
            content_type="application/json",
            data=data,
        )
