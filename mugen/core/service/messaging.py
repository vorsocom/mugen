"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from types import SimpleNamespace

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _thread_version: int = 1

    _thread_list_version: int = 1

    _cp_extensions: list[ICPExtension] = []

    _ct_extensions: list[ICTExtension] = []

    _ctx_extensions: list[ICTXExtension] = []

    _mh_extensions: list[IMHExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    _rpp_extensions: list[IRPPExtension] = []

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
    ) -> None:
        self._config = config
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

    async def handle_audio_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle audio
            # messages.
            if "audio" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: audio.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an audio file.",
            message_context=handler_responses,
        )

    async def handle_file_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle file
            # messages.
            if "file" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: file.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded a file.",
            message_context=handler_responses,
        )

    async def handle_image_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle image
            # messages.
            if "image" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: image.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an image file.",
            message_context=handler_responses,
        )

    async def handle_text_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: str,
        message_context: list[str] = None,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle text
            # messages.
            if "text" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
                message_context=message_context,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: text.",
                }
            ]

        return handler_responses

    async def handle_video_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle video
            # messages.
            if "video" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: video.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded video file.",
            message_context=handler_responses,
        )

    @property
    def cp_extensions(self) -> list[ICPExtension]:
        return self._cp_extensions

    @property
    def ct_extensions(self) -> list[ICTExtension]:
        return self._ct_extensions

    @property
    def ctx_extensions(self) -> list[ICTXExtension]:
        return self._ctx_extensions

    @property
    def mh_extensions(self) -> list[IMHExtension]:
        return self._mh_extensions

    @property
    def rag_extensions(self) -> list[IRAGExtension]:
        return self._rag_extensions

    @property
    def rpp_extensions(self) -> list[IRPPExtension]:
        return self._rpp_extensions

    def register_cp_extension(self, ext: ICPExtension) -> None:
        self._cp_extensions.append(ext)

    def register_ct_extension(self, ext: ICTExtension) -> None:
        self._ct_extensions.append(ext)

    def register_ctx_extension(self, ext: ICTXExtension) -> None:
        self._ctx_extensions.append(ext)

    def register_mh_extension(self, ext: IMHExtension) -> None:
        self._mh_extensions.append(ext)

    def register_rag_extension(self, ext: IRAGExtension) -> None:
        self._rag_extensions.append(ext)

    def register_rpp_extension(self, ext: IRPPExtension) -> None:
        self._rpp_extensions.append(ext)
