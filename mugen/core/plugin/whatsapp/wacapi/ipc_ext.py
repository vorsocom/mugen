"""Provides an implementation of IIPCExtension for WhatsApp Cloud API support."""

__all__ = ["WhatsAppWACAPIIPCExtension"]

import asyncio
import json
from types import SimpleNamespace

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core import di


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    # pylint: disable=too-many-arguments
    # # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace = di.container.config,
        logging_gateway: ILoggingGateway = di.container.logging_gateway,
        messaging_service: IMessagingService = di.container.messaging_service,
        user_service: IUserService = di.container.user_service,
        whatsapp_client: IWhatsAppClient = di.container.whatsapp_client,
    ) -> None:
        self._client = whatsapp_client
        self._config = config
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "whatsapp_wacapi_event",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["whatsapp"]

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.debug(
            f"WhatsAppWACAPIIPCExtension: Executing command: {payload['command']}"
        )
        match payload["command"]:
            case "whatsapp_wacapi_event":
                await self._wacapi_event(payload)
                return
            case _:
                ...

    async def _wacapi_event(self, payload: dict) -> None:
        """Process WhatsApp Cloud API event."""
        # Get message data.
        event = payload["data"]
        if "messages" in event["entry"][0]["changes"][0]["value"].keys():
            contact = event["entry"][0]["changes"][0]["value"]["contacts"][0]
            message = event["entry"][0]["changes"][0]["value"]["messages"][0]
            sender = contact["wa_id"]

            if self._config.mugen.beta.active:
                beta_users: list = self._config.whatsapp.beta.users
                if sender not in beta_users:
                    await self._client.send_text_message(
                        message=self._config.mugen.beta.message,
                        recipient=sender,
                    )
                    await payload["response_queue"].put({"response": "OK"})
                    return

            # Add user to list of known users if required.
            known_users = self._user_service.get_known_users_list()
            if sender not in known_users.keys():
                self._logging_gateway.debug(f"New WhatsApp contact: {sender}")
                self._user_service.add_known_user(
                    sender,
                    contact["profile"]["name"],
                    sender,
                )

            message_responses: list[dict] = []
            match message["type"]:
                case "audio":
                    # Allow messaging service to process the message.
                    get_media_url = await self._client.retrieve_media_url(
                        message["audio"]["id"],
                    )
                    if get_media_url is not None:
                        media_url = json.loads(get_media_url)
                        get_media = await self._client.download_media(
                            media_url["url"],
                            message["audio"]["mime_type"],
                        )

                        if get_media is not None:
                            message_responses = (
                                await self._messaging_service.handle_audio_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message={
                                        "message": message,
                                        "file": get_media,
                                    },
                                )
                            )
                case "document":
                    # Allow messaging service to process the message.
                    get_media_url = await self._client.retrieve_media_url(
                        message["document"]["id"],
                    )
                    if get_media_url is not None:
                        media_url = json.loads(get_media_url)
                        get_media = await self._client.download_media(
                            media_url["url"],
                            message["document"]["mime_type"],
                        )

                        if get_media is not None:
                            message_responses = (
                                await self._messaging_service.handle_file_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message={
                                        "message": message,
                                        "file": get_media,
                                    },
                                )
                            )
                case "image":
                    # Allow messaging service to process the message.
                    get_media_url = await self._client.retrieve_media_url(
                        message["image"]["id"],
                    )
                    if get_media_url is not None:
                        media_url = json.loads(get_media_url)
                        get_media = await self._client.download_media(
                            media_url["url"],
                            message["image"]["mime_type"],
                        )

                        if get_media is not None:
                            message_responses = (
                                await self._messaging_service.handle_image_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message={
                                        "message": message,
                                        "file": get_media,
                                    },
                                )
                            )
                case "text":
                    # Allow messaging service to process the message.
                    message_responses = (
                        await self._messaging_service.handle_text_message(
                            "whatsapp",
                            room_id=sender,
                            sender=sender,
                            message=message["text"]["body"],
                        )
                    )
                case "video":
                    # Allow messaging service to process the message.
                    get_media_url = await self._client.retrieve_media_url(
                        message["video"]["id"],
                    )
                    if get_media_url is not None:
                        media_url = json.loads(get_media_url)
                        get_media = await self._client.download_media(
                            media_url["url"],
                            message["video"]["mime_type"],
                        )

                        if get_media is not None:
                            message_responses = (
                                await self._messaging_service.handle_video_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message={
                                        "message": message,
                                        "file": get_media,
                                    },
                                )
                            )
                case _:
                    await self._call_message_handlers(
                        message=message,
                        message_type=message["type"],
                        sender=sender,
                    )

            self._logging_gateway.debug("Send responses to user.")
            for response in message_responses:
                # Audio.
                if response["type"] == "audio":
                    upload = await self._client.upload_media(
                        response["file"]["uri"], response["file"]["type"]
                    )
                    upload_response = json.loads(upload)

                    if "error" in upload_response.keys():
                        self._logging_gateway.debug("Audio upload failed.")
                        self._logging_gateway.error(upload_response["error"])
                    else:
                        send = await self._client.send_audio_message(
                            audio={
                                "id": upload_response["id"],
                            },
                            recipient=sender,
                        )
                        data: dict = json.loads(send)

                        if "error" in data.keys():
                            self._logging_gateway.error("Send audio to user failed.")
                            self._logging_gateway.error(data["error"])
                # Document.
                if response["type"] == "file":
                    upload = await self._client.upload_media(
                        response["file"]["uri"], response["file"]["type"]
                    )
                    upload_response = json.loads(upload)

                    if "error" in upload_response.keys():
                        self._logging_gateway.debug("Document upload failed.")
                        self._logging_gateway.error(upload_response["error"])
                    else:
                        send = await self._client.send_document_message(
                            document={
                                "id": upload_response["id"],
                                "filename": response["file"]["name"],
                            },
                            recipient=sender,
                        )
                        data: dict = json.loads(send)

                        if "error" in data.keys():
                            self._logging_gateway.error("Send document to user failed.")
                            self._logging_gateway.error(data["error"])
                # Image.
                if response["type"] == "image":
                    upload = await self._client.upload_media(
                        response["file"]["uri"], response["file"]["type"]
                    )
                    upload_response = json.loads(upload)

                    if "error" in upload_response.keys():
                        self._logging_gateway.debug("Image upload failed.")
                        self._logging_gateway.error(upload_response["error"])
                    else:
                        send = await self._client.send_image_message(
                            image={
                                "id": upload_response["id"],
                            },
                            recipient=sender,
                        )
                        data: dict = json.loads(send)

                        if "error" in data.keys():
                            self._logging_gateway.error("Send image to user failed.")
                            self._logging_gateway.error(data["error"])
                # Text.
                if response["type"] == "text":
                    send = await self._client.send_text_message(
                        message=response["content"],
                        recipient=sender,
                    )
                    data: dict = json.loads(send)

                    if "error" in data.keys():
                        self._logging_gateway.error("Send text to user failed.")
                        self._logging_gateway.error(data["error"])
                # Video.
                if response["type"] == "video":
                    upload = await self._client.upload_media(
                        response["file"]["uri"], response["file"]["type"]
                    )
                    upload_response = json.loads(upload)

                    if "error" in upload_response.keys():
                        self._logging_gateway.debug("Video upload failed.")
                        self._logging_gateway.error(upload_response["error"])
                    else:
                        send = await self._client.send_video_message(
                            video={
                                "id": upload_response["id"],
                            },
                            recipient=sender,
                        )
                        data: dict = json.loads(send)

                        if "error" in data.keys():
                            self._logging_gateway.error("Send video to user failed.")
                            self._logging_gateway.error(data["error"])
        elif "statuses" in event["entry"][0]["changes"][0]["value"].keys():
            # Process message sent, delivered, and read statuses.
            await self._call_message_handlers(
                message=event["entry"][0]["changes"][0]["value"]["statuses"][0],
                message_type="status",
            )

        await payload["response_queue"].put({"response": "OK"})

    async def _call_message_handlers(
        self,
        message: dict,
        message_type: str,
        sender: str = None,
    ) -> None:
        hits: int = 0
        message_handlers: list[IMHExtension] = self._messaging_service.mh_extensions
        for handler in message_handlers:
            if (
                handler.platform_supported("whatsapp")
            ) and message_type in handler.message_types:
                await asyncio.gather(
                    asyncio.create_task(
                        handler.handle_message(
                            room_id=sender,
                            sender=sender,
                            message=message,
                        )
                    )
                )
                hits += 1
        if hits == 0:
            self._logging_gateway.debug(f"Unsupported message type: {message_type}.")
            if sender:
                await self._client.send_text_message(
                    message="Unsupported message type..",
                    recipient=sender,
                    reply_to=message["id"],
                )
