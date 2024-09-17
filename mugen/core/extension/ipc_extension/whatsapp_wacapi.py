"""Provides an implementation of IIPCExtension for WhatsApp Cloud API support."""

__all__ = ["WhatsAppWACAPIIPCExtension"]

import asyncio
import json
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide

from mugen.core.contract.ipc_extension import IIPCExtension
from mugen.core.contract.logging_gateway import ILoggingGateway
from mugen.core.contract.messaging_service import IMessagingService
from mugen.core.contract.mh_extension import IMHExtension
from mugen.core.contract.user_service import IUserService
from mugen.core.contract.whatsapp_client import IWhatsAppClient
from mugen.core.di import DIContainer


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    # pylint: disable=too-many-arguments
    @inject
    def __init__(
        self,
        config: dict = Provide[DIContainer.config],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
        messaging_service: IMessagingService = Provide[DIContainer.messaging_service],
        user_service: IUserService = Provide[DIContainer.user_service],
        whatsapp_client: IWhatsAppClient = Provide[DIContainer.whatsapp_client],
    ) -> None:
        self._client = whatsapp_client
        self._config = SimpleNamespace(**config)
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

            if self._config.mugen_limited_beta.lower() in (
                "true",
                "1",
            ):
                beta_users: list = json.loads(self._config.whatsapp_limited_beta_users)
                if sender not in beta_users:
                    await self._client.send_text_message(
                        message=(
                            "This application is in limted beta and you are not on the"
                            " beta list."
                        ),
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

            ##!! Only process text messages for now.
            match message["type"]:
                case "text":
                    # Allow messaging service to process the message.
                    response = await self._messaging_service.handle_text_message(
                        "whatsapp",
                        room_id=sender,
                        sender=sender,
                        content=message["text"]["body"],
                    )

                    # Send assistant response to user.
                    if response not in ("", None):
                        self._logging_gateway.debug("Send response to user.")
                        send = await self._client.send_text_message(
                            message=response,
                            recipient=sender,
                        )
                        data: dict = json.loads(send)

                        if "error" in data.keys():
                            self._logging_gateway.error("Send response to user failed.")
                            self._logging_gateway.error(data["error"])
                        else:
                            self._logging_gateway.debug(
                                "Send response to user successful."
                            )
                case _:
                    hits: int = 0
                    message_handlers: list[IMHExtension] = (
                        self._messaging_service.mh_extensions
                    )
                    for handler in message_handlers:
                        if (
                            handler.platforms == [] or "whatsapp" in handler.platforms
                        ) and message["type"] in handler.message_types:
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
                        self._logging_gateway.debug(
                            f"Unsupported message type: {message['type']}."
                        )
                        await self._client.send_text_message(
                            message=(
                                "This platform only supports text-based communication"
                                " at the moment."
                            ),
                            recipient=sender,
                            reply_to=message["id"],
                        )
        elif "statuses" in event["entry"][0]["changes"][0]["value"].keys():
            # Process message sent, delivered, and read statuses.
            pass

        await payload["response_queue"].put({"response": "OK"})
