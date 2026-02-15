"""Provides an implementation of IIPCExtension for WhatsApp Cloud API support."""

__all__ = ["WhatsAppWACAPIIPCExtension"]

import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core import di


def _whatsapp_client_provider():
    return di.container.whatsapp_client


def _config_provider():
    return di.container.config


def _logging_gateway_provider():
    return di.container.logging_gateway


def _keyval_storage_gateway_provider():
    return di.container.keyval_storage_gateway


def _messaging_service_provider():
    return di.container.messaging_service


def _user_service_provider():
    return di.container.user_service


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    _seen_event_keys_key = "whatsapp_wacapi_seen_events"
    _seen_event_keys_max = 1024

    # pylint: disable=too-many-arguments
    # # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        keyval_storage_gateway: IKeyValStorageGateway | None = None,
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
        self._keyval_storage_gateway = (
            keyval_storage_gateway
            if keyval_storage_gateway is not None
            else _keyval_storage_gateway_provider()
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

    def _extract_api_data(self, payload: dict | None, context: str) -> dict | None:
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

        return data

    @staticmethod
    def _extract_user_text(message: dict) -> str | None:
        message_type = message.get("type")

        if message_type == "text":
            text_body = message.get("text", {}).get("body")
            return text_body if isinstance(text_body, str) else None

        if message_type == "button":
            button = message.get("button", {})
            button_text = button.get("text")
            if isinstance(button_text, str) and button_text != "":
                return button_text
            payload = button.get("payload")
            return payload if isinstance(payload, str) else None

        if message_type != "interactive":
            return None

        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            button_reply = interactive.get("button_reply", {})
            title = button_reply.get("title")
            if isinstance(title, str) and title != "":
                return title
            button_id = button_reply.get("id")
            return button_id if isinstance(button_id, str) else None

        if interactive_type == "list_reply":
            list_reply = interactive.get("list_reply", {})
            title = list_reply.get("title")
            if isinstance(title, str) and title != "":
                return title
            list_id = list_reply.get("id")
            return list_id if isinstance(list_id, str) else None

        if interactive_type == "nfm_reply":
            nfm_reply = interactive.get("nfm_reply", {})
            response_json = nfm_reply.get("response_json")
            if isinstance(response_json, str):
                return response_json
            if isinstance(response_json, dict):
                return json.dumps(response_json)

        return None

    def _load_seen_event_keys(self) -> list[str]:
        payload = self._keyval_storage_gateway.get(self._seen_event_keys_key)
        if not isinstance(payload, str):
            return []
        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    @staticmethod
    def _build_event_dedupe_key(event_type: str, event_payload: dict) -> str:
        payload = json.dumps(event_payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{event_type}:{payload_hash}"

    def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        seen_event_keys = self._load_seen_event_keys()
        if dedupe_key in seen_event_keys:
            return True
        seen_event_keys.append(dedupe_key)
        if len(seen_event_keys) > self._seen_event_keys_max:
            seen_event_keys = seen_event_keys[-self._seen_event_keys_max :]
        self._keyval_storage_gateway.put(
            self._seen_event_keys_key,
            json.dumps(seen_event_keys),
        )
        return False

    @staticmethod
    def _get_contact_for_sender(contacts: list, sender: str | None) -> dict | None:
        if not isinstance(contacts, list):
            return None

        for contact in contacts:
            if (
                isinstance(contact, dict)
                and isinstance(sender, str)
                and contact.get("wa_id") == sender
            ):
                return contact

        for contact in contacts:
            if isinstance(contact, dict):
                return contact

        return None

    async def _process_message_event(self, event_value: dict, message: dict) -> None:
        started = time.perf_counter()
        correlation_id = message.get("id")
        self._logging_gateway.debug(
            f"[cid={correlation_id}] Process WhatsApp message event "
            f"type={message.get('type')}."
        )
        sender = message.get("from")
        contact = self._get_contact_for_sender(event_value.get("contacts"), sender)

        if not isinstance(sender, str) or sender == "":
            candidate_sender = (
                contact.get("wa_id") if isinstance(contact, dict) else None
            )
            sender = candidate_sender if isinstance(candidate_sender, str) else None

        if not isinstance(sender, str) or sender == "":
            self._logging_gateway.error("Malformed WhatsApp message payload.")
            return

        if self._is_duplicate_event("message", message):
            self._logging_gateway.debug("Skip duplicate WhatsApp message event.")
            return

        if self._config.mugen.beta.active:
            beta_users: list = self._config.whatsapp.beta.users
            if sender not in beta_users:
                await self._client.send_text_message(
                    message=self._config.mugen.beta.message,
                    recipient=sender,
                )
                return

        known_users = self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender not in known_users.keys():
            profile_name = sender
            if isinstance(contact, dict):
                contact_profile = contact.get("profile")
                if isinstance(contact_profile, dict):
                    contact_name = contact_profile.get("name")
                    if isinstance(contact_name, str) and contact_name != "":
                        profile_name = contact_name
            self._logging_gateway.debug(f"New WhatsApp contact: {sender}")
            self._user_service.add_known_user(
                sender,
                profile_name,
                sender,
            )

        message_responses: list[dict] | None = []
        try:
            match message["type"]:
                case "audio":
                    get_media_url = await self._client.retrieve_media_url(
                        message["audio"]["id"],
                    )
                    media_url = self._extract_api_data(get_media_url, "audio media URL")
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
                    media_url = self._extract_api_data(
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
                    media_url = self._extract_api_data(get_media_url, "image media URL")
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
                case "text" | "interactive" | "button":
                    text_message = self._extract_user_text(message)
                    if text_message is None:
                        await self._call_message_handlers(
                            message=message,
                            message_type=message["type"],
                            sender=sender,
                        )
                    else:
                        message_responses = (
                            await self._messaging_service.handle_text_message(
                                "whatsapp",
                                room_id=sender,
                                sender=sender,
                                message=text_message,
                            )
                        )
                case "video":
                    get_media_url = await self._client.retrieve_media_url(
                        message["video"]["id"],
                    )
                    media_url = self._extract_api_data(get_media_url, "video media URL")
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
        except (KeyError, TypeError):
            self._logging_gateway.error("Malformed WhatsApp message payload.")
            return

        self._logging_gateway.debug("Send responses to user.")
        for response in message_responses or []:
            await self._send_response_to_user(response=response, sender=sender)
        latency_ms = (time.perf_counter() - started) * 1000
        self._logging_gateway.debug(
            f"[cid={correlation_id}] WhatsApp message event completed "
            f"latency_ms={latency_ms:.2f}."
        )

    async def _process_status_event(self, status: dict) -> None:
        started = time.perf_counter()
        correlation_id = status.get("id")
        self._logging_gateway.debug(
            f"[cid={correlation_id}] Process WhatsApp status event "
            f"status={status.get('status')}."
        )
        if self._is_duplicate_event("status", status):
            self._logging_gateway.debug("Skip duplicate WhatsApp status event.")
            return

        await self._call_message_handlers(
            message=status,
            message_type="status",
        )
        latency_ms = (time.perf_counter() - started) * 1000
        self._logging_gateway.debug(
            f"[cid={correlation_id}] WhatsApp status event completed "
            f"latency_ms={latency_ms:.2f}."
        )

    async def _upload_response_media(self, response: dict, context: str) -> dict | None:
        file_data = response.get("file")
        if not isinstance(file_data, dict):
            self._logging_gateway.error(f"Missing file payload for {context} response.")
            return None

        uri = file_data.get("uri")
        content_type = file_data.get("type")
        if not isinstance(uri, str) or not isinstance(content_type, str):
            self._logging_gateway.error(f"Invalid file payload for {context} response.")
            return None

        upload_response = await self._client.upload_media(uri, content_type)
        upload_data = self._extract_api_data(upload_response, f"{context} upload")
        if upload_data is None:
            return None

        media_id = upload_data.get("id")
        if not isinstance(media_id, str) or media_id == "":
            self._logging_gateway.error(f"{context} upload did not return media id.")
            return None

        return {
            "id": media_id,
            "file": file_data,
        }

    async def _send_response_to_user(self, response: dict, sender: str) -> None:
        response_type = response.get("type")
        reply_to = response.get("reply_to")
        if not isinstance(reply_to, str):
            reply_to = None

        if response_type == "audio":
            uploaded = await self._upload_response_media(response, "audio")
            if uploaded is None:
                return
            send_result = await self._client.send_audio_message(
                audio={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "audio send")
            return

        if response_type == "file":
            uploaded = await self._upload_response_media(response, "document")
            if uploaded is None:
                return
            document = {
                "id": uploaded["id"],
            }
            file_name = uploaded["file"].get("name")
            if isinstance(file_name, str) and file_name != "":
                document["filename"] = file_name
            send_result = await self._client.send_document_message(
                document=document,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "document send")
            return

        if response_type == "image":
            uploaded = await self._upload_response_media(response, "image")
            if uploaded is None:
                return
            send_result = await self._client.send_image_message(
                image={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "image send")
            return

        if response_type == "video":
            uploaded = await self._upload_response_media(response, "video")
            if uploaded is None:
                return
            send_result = await self._client.send_video_message(
                video={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "video send")
            return

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return
            send_result = await self._client.send_text_message(
                message=content,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "text send")
            return

        if response_type == "contacts":
            contacts = response.get("contacts", response.get("content"))
            send_result = await self._client.send_contacts_message(
                contacts=contacts,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "contacts send")
            return

        if response_type == "location":
            location = response.get("location", response.get("content"))
            if not isinstance(location, dict):
                self._logging_gateway.error("Missing location payload in response.")
                return
            send_result = await self._client.send_location_message(
                location=location,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "location send")
            return

        if response_type == "interactive":
            interactive = response.get("interactive", response.get("content"))
            if not isinstance(interactive, dict):
                self._logging_gateway.error("Missing interactive payload in response.")
                return
            send_result = await self._client.send_interactive_message(
                interactive=interactive,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "interactive send")
            return

        if response_type == "template":
            template = response.get("template", response.get("content"))
            if not isinstance(template, dict):
                self._logging_gateway.error("Missing template payload in response.")
                return
            send_result = await self._client.send_template_message(
                template=template,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "template send")
            return

        if response_type == "sticker":
            sticker = response.get("sticker", response.get("content"))
            if not isinstance(sticker, dict):
                self._logging_gateway.error("Missing sticker payload in response.")
                return
            send_result = await self._client.send_sticker_message(
                sticker=sticker,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "sticker send")
            return

        if response_type == "reaction":
            reaction = response.get("reaction", response.get("content"))
            if not isinstance(reaction, dict):
                self._logging_gateway.error("Missing reaction payload in response.")
                return
            send_result = await self._client.send_reaction_message(
                reaction=reaction,
                recipient=sender,
            )
            self._extract_api_data(send_result, "reaction send")
            return

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")

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
        started = time.perf_counter()
        response_queue = payload.get("response_queue")
        try:
            event = payload["data"]
            entries = event["entry"]
            if not isinstance(entries, list):
                raise TypeError

            found_event_payload = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                changes = entry.get("changes")
                if not isinstance(changes, list):
                    continue

                for change in changes:
                    if not isinstance(change, dict):
                        continue

                    event_value = change.get("value")
                    if not isinstance(event_value, dict):
                        continue

                    found_event_payload = True

                    messages = event_value.get("messages")
                    if isinstance(messages, list):
                        for message in messages:
                            if not isinstance(message, dict):
                                self._logging_gateway.error(
                                    "Malformed WhatsApp message payload."
                                )
                                continue
                            await self._process_message_event(event_value, message)

                    statuses = event_value.get("statuses")
                    if isinstance(statuses, list):
                        for status in statuses:
                            if not isinstance(status, dict):
                                self._logging_gateway.error(
                                    "Malformed WhatsApp status payload."
                                )
                                continue
                            await self._process_status_event(status)

            if not found_event_payload:
                raise TypeError
        except (KeyError, TypeError):
            self._logging_gateway.error("Malformed WhatsApp event payload.")
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"WhatsApp webhook event processing latency_ms={latency_ms:.2f}."
            )
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
