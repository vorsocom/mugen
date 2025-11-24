"""Provides an implementation of IWhatsApp client."""

__all__ = ["DefaultWhatsAppClient"]

from http import HTTPMethod
from io import BytesIO
import json
import mimetypes
import tempfile
from types import SimpleNamespace

import aiohttp
import aiofiles

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


# pylint: disable=too-many-instance-attributes
class DefaultWhatsAppClient(IWhatsAppClient):
    """An implementation of IWhatsAppClient."""

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

        self._api_base_path = (
            f"{self._config.whatsapp.graphapi.base_url}/"
            f"{self._config.whatsapp.graphapi.version}"
        )

        self._api_media_path = f"{self._config.whatsapp.business.phone_number_id}/media"

        self._api_messages_path = (
            f"{self._config.whatsapp.business.phone_number_id}/messages"
        )

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.init")
        self._client_session = aiohttp.ClientSession()

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultWhatsAppClient.close")
        await self._client_session.close()

    async def delete_media(self, media_id: str) -> str | None:
        return await self._call_api(media_id, method=HTTPMethod.DELETE)

    async def download_media(self, media_url: str, mimetype: str) -> str | None:
        return await self._download_file_http(media_url, mimetype)

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
            "Authorization": f"Bearer {self._config.whatsapp.graphapi.access_token}",
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

    async def _download_file_http(self, url: str, mimetype: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self._config.whatsapp.graphapi.access_token}",
        }

        kwargs = {
            "headers": headers,
        }

        try:
            response = await self._client_session.get(url, **kwargs)

            if response.status == 200:
                extension = mimetypes.guess_extension(mimetype.split(";")[0].strip())
                if extension:
                    with tempfile.NamedTemporaryFile(
                        suffix=extension,
                        delete=False,
                    ) as tf:
                        async with aiofiles.open(tf.name, "wb") as af:
                            await af.write(await response.read())
                            return tf.name
        except aiohttp.ClientConnectionError as e:
            self._logging_gateway.error(str(e))

    async def _send_message(self, data: dict) -> str | None:
        """Utility for all message functions."""
        return await self._call_api(
            path=self._api_messages_path,
            content_type="application/json",
            data=data,
        )
