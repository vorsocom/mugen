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


def _whatsapp_client_provider():
    return di.container.whatsapp_client


def _config_provider():
    return di.container.config


def _logging_gateway_provider():
    return di.container.logging_gateway


def _messaging_service_provider():
    return di.container.messaging_service


def _user_service_provider():
    return di.container.user_service


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    # pylint: disable=too-many-arguments
    # # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        whatsapp_client: IWhatsAppClient | None = None,
    ) -> None:
        self._client = (
            whatsapp_client
            if whatsapp_client is not None
            else _whatsapp_client_provider()
        )
        self._config = config if config is not None else _config_provider()
        self._logging_gateway = (
            logging_gateway
            if logging_gateway is not None
            else _logging_gateway_provider()
        )
        self._messaging_service = (
            messaging_service
            if messaging_service is not None
            else _messaging_service_provider()
        )
        self._user_service = (
            user_service if user_service is not None else _user_service_provider()
        )

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "whatsapp_wacapi_event",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["whatsapp"]

    def _parse_json_dict(self, payload: str | None, context: str) -> dict | None:
        if payload is None:
            self._logging_gateway.error(f"Missing payload for {context}.")
            return None

        try:
            parsed = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            self._logging_gateway.error(f"Invalid JSON payload for {context}.")
            return None

        if not isinstance(parsed, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        return parsed

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
        response_queue = payload.get("response_queue")
        try:
            event = payload["data"]
            event_value = event["entry"][0]["changes"][0]["value"]
            if "messages" in event_value.keys():
                contact = event_value["contacts"][0]
                message = event_value["messages"][0]
                sender = contact["wa_id"]

                if self._config.mugen.beta.active:
                    beta_users: list = self._config.whatsapp.beta.users
                    if sender not in beta_users:
                        await self._client.send_text_message(
                            message=self._config.mugen.beta.message,
                            recipient=sender,
                        )
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

                message_responses: list[dict] | None = []
                match message["type"]:
                    case "audio":
                        get_media_url = await self._client.retrieve_media_url(
                            message["audio"]["id"],
                        )
                        media_url = self._parse_json_dict(get_media_url, "audio media URL")
                        if media_url and "url" in media_url.keys():
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
                        get_media_url = await self._client.retrieve_media_url(
                            message["document"]["id"],
                        )
                        media_url = self._parse_json_dict(
                            get_media_url, "document media URL"
                        )
                        if media_url and "url" in media_url.keys():
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
                        get_media_url = await self._client.retrieve_media_url(
                            message["image"]["id"],
                        )
                        media_url = self._parse_json_dict(get_media_url, "image media URL")
                        if media_url and "url" in media_url.keys():
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
                        message_responses = await self._messaging_service.handle_text_message(
                            "whatsapp",
                            room_id=sender,
                            sender=sender,
                            message=message["text"]["body"],
                        )
                    case "video":
                        get_media_url = await self._client.retrieve_media_url(
                            message["video"]["id"],
                        )
                        media_url = self._parse_json_dict(get_media_url, "video media URL")
                        if media_url and "url" in media_url.keys():
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
                for response in message_responses or []:
                    # Audio.
                    if response["type"] == "audio":
                        upload = await self._client.upload_media(
                            response["file"]["uri"], response["file"]["type"]
                        )
                        upload_response = self._parse_json_dict(upload, "audio upload")
                        if upload_response is None:
                            continue

                        if "error" in upload_response.keys():
                            self._logging_gateway.debug("Audio upload failed.")
                            self._logging_gateway.error(upload_response["error"])
                        elif "id" in upload_response.keys():
                            send = await self._client.send_audio_message(
                                audio={
                                    "id": upload_response["id"],
                                },
                                recipient=sender,
                            )
                            data = self._parse_json_dict(send, "audio send")

                            if data and "error" in data.keys():
                                self._logging_gateway.error("Send audio to user failed.")
                                self._logging_gateway.error(data["error"])
                    # Document.
                    if response["type"] == "file":
                        upload = await self._client.upload_media(
                            response["file"]["uri"], response["file"]["type"]
                        )
                        upload_response = self._parse_json_dict(upload, "document upload")
                        if upload_response is None:
                            continue

                        if "error" in upload_response.keys():
                            self._logging_gateway.debug("Document upload failed.")
                            self._logging_gateway.error(upload_response["error"])
                        elif "id" in upload_response.keys():
                            send = await self._client.send_document_message(
                                document={
                                    "id": upload_response["id"],
                                    "filename": response["file"]["name"],
                                },
                                recipient=sender,
                            )
                            data = self._parse_json_dict(send, "document send")

                            if data and "error" in data.keys():
                                self._logging_gateway.error("Send document to user failed.")
                                self._logging_gateway.error(data["error"])
                    # Image.
                    if response["type"] == "image":
                        upload = await self._client.upload_media(
                            response["file"]["uri"], response["file"]["type"]
                        )
                        upload_response = self._parse_json_dict(upload, "image upload")
                        if upload_response is None:
                            continue

                        if "error" in upload_response.keys():
                            self._logging_gateway.debug("Image upload failed.")
                            self._logging_gateway.error(upload_response["error"])
                        elif "id" in upload_response.keys():
                            send = await self._client.send_image_message(
                                image={
                                    "id": upload_response["id"],
                                },
                                recipient=sender,
                            )
                            data = self._parse_json_dict(send, "image send")

                            if data and "error" in data.keys():
                                self._logging_gateway.error("Send image to user failed.")
                                self._logging_gateway.error(data["error"])
                    # Text.
                    if response["type"] == "text":
                        send = await self._client.send_text_message(
                            message=response["content"],
                            recipient=sender,
                        )
                        data = self._parse_json_dict(send, "text send")

                        if data and "error" in data.keys():
                            self._logging_gateway.error("Send text to user failed.")
                            self._logging_gateway.error(data["error"])
                    # Video.
                    if response["type"] == "video":
                        upload = await self._client.upload_media(
                            response["file"]["uri"], response["file"]["type"]
                        )
                        upload_response = self._parse_json_dict(upload, "video upload")
                        if upload_response is None:
                            continue

                        if "error" in upload_response.keys():
                            self._logging_gateway.debug("Video upload failed.")
                            self._logging_gateway.error(upload_response["error"])
                        elif "id" in upload_response.keys():
                            send = await self._client.send_video_message(
                                video={
                                    "id": upload_response["id"],
                                },
                                recipient=sender,
                            )
                            data = self._parse_json_dict(send, "video send")

                            if data and "error" in data.keys():
                                self._logging_gateway.error("Send video to user failed.")
                                self._logging_gateway.error(data["error"])
            elif "statuses" in event_value.keys():
                # Process message sent, delivered, and read statuses.
                await self._call_message_handlers(
                    message=event_value["statuses"][0],
                    message_type="status",
                )
        except (IndexError, KeyError, TypeError):
            self._logging_gateway.error("Malformed WhatsApp event payload.")
        finally:
            if response_queue is not None:
                await response_queue.put({"response": "OK"})

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
