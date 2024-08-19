"""
Builds agent application.
"""

import asyncio
import os

from nio import (
    AsyncClient,
    InviteAliasEvent,
    InviteMemberEvent,
    InviteNameEvent,
    RoomMessageText,
    SyncResponse,
    RoomCreateEvent,
)

from app.nio.auth import login
from app.nio.callbacks import Callbacks, SYNC_KEY
from app.nio.client import CustomAsyncClient

from app.contract.completion_gateway import ICompletionGateway
from app.contract.ipc_service import IIPCService
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.messaging_service import IMessagingService
from app.contract.nlp_service import INLPService
from app.contract.platform_gateway import IPlatformGateway
from app.contract.user_service import IUserService


def load_config(basedir: str, keyval_storage_gateway: IKeyValStorageGateway) -> None:
    """Load configuration value from environment file to dbm storage."""

    keyval_storage_gateway.put(
        "gloria_limited_beta",
        os.getenv("GLORIA_LIMITED_BETA"),
    )
    keyval_storage_gateway.put(
        "gloria_limited_beta_users",
        os.getenv("GLORIA_LIMITED_BETA_USERS"),
    )
    keyval_storage_gateway.put(
        "gloria_allowed_domains",
        os.getenv("GLORIA_ALLOWED_DOMAINS"),
    )
    keyval_storage_gateway.put(
        "gloria_meeting_expiry_time",
        os.getenv("GLORIA_MEETING_EXPIRY_TIME"),
    )

    with open(f"{basedir}/conf/persona.txt", encoding="utf8") as f:
        keyval_storage_gateway.put("matrix_assistant_persona", f.read())

    keyval_storage_gateway.put("matrix_homeserver", os.getenv("MATRIX_HOMESERVER"))
    keyval_storage_gateway.put("matrix_client_user", os.getenv("MATRIX_CLIENT_USER"))
    keyval_storage_gateway.put(
        "matrix_client_password", os.getenv("MATRIX_CLIENT_PASSWORD")
    )
    keyval_storage_gateway.put(
        "matrix_client_device_name", os.getenv("MATRIX_CLIENT_DEVICE_NAME")
    )
    keyval_storage_gateway.put(
        "matrix_agent_display_name", os.getenv("MATRIX_AGENT_DISPLAY_NAME")
    )

    keyval_storage_gateway.put("groq_api_key", os.getenv("GROQ_API_KEY"))
    keyval_storage_gateway.put(
        "groq_api_classification_model", os.getenv("GROQ_API_CLASSIFICATION_MODEL")
    )
    keyval_storage_gateway.put(
        "groq_api_completion_model", os.getenv("GROQ_API_COMPLETION_MODEL")
    )

    keyval_storage_gateway.put("qdrant_api_key", os.getenv("QDRANT_API_KEY"))
    keyval_storage_gateway.put("qdrant_endpoint_url", os.getenv("QDRANT_ENDPOINT_URL"))


async def leave_test_rooms(client: AsyncClient) -> None:
    """Leave all rooms joined by agent while testing."""
    rooms = await client.joined_rooms()
    for room_id in rooms.rooms:
        members = await client.joined_members(room_id)
        to_kick = [x.user_id for x in members.members if x.user_id != client.user_id]
        for user_id in to_kick:
            await client.room_kick(room_id, user_id)
        await client.room_leave(room_id)


# pylint: disable=too-many-locals
async def run_assistant(basedir: str, log_level: int, ipc_queue: asyncio.Queue) -> None:
    """Application entrypoint."""
    # Initialise logger.
    logging_gateway = ILoggingGateway.instance(
        logging_module="app.gateway.default_logging_gateway", log_level=log_level
    )

    # Initialise matrix-nio async client.
    async with CustomAsyncClient(
        os.getenv("MATRIX_HOMESERVER"),
        os.getenv("MATRIX_CLIENT_USER"),
        ipc_queue=ipc_queue,
        logging_gateway=logging_gateway,
    ) as client:
        # Initialise storage
        keyval_storage_gateway = IKeyValStorageGateway.instance(
            storage_module="app.gateway.dbm_keyval_storage_gateway",
            storage_path=f"{basedir}/data/storage.db",
            logging_gateway=logging_gateway,
        )

        # Initialise Groq completion gateway.
        completion_gateway = ICompletionGateway.instance(
            completion_module="app.gateway.groq_completion_gateway",
            api_key=os.getenv("GROQ_API_KEY"),
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        # Initialise NLP service.
        nlp_service = INLPService.instance(
            service_module="app.service.default_nlp_service",
            logging_gateway=logging_gateway,
        )

        # Initialise Qdrant knowledge retrieval gateway
        knowledge_retrieval_gateway = IKnowledgeRetrievalGateway.instance(
            knowledge_retrieval_module="app.gateway.qdrant_knowledge_retrieval_gateway",
            api_key=os.getenv("QDRANT_API_KEY"),
            endpoint_url=os.getenv("QDRANT_ENDPOINT_URL"),
            logging_gateway=logging_gateway,
            nlp_service=nlp_service,
        )

        # Initialise platform gateway.
        platform_gateway = IPlatformGateway.instance(
            platform_module="app.gateway.matrix_platform_gateway",
            client=client,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        # Initialise meeting service
        meeting_service = IMeetingService.instance(
            service_module="app.service.default_meeting_service",
            client=client,
            completion_gateway=completion_gateway,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            platform_gateway=platform_gateway,
        )

        # Initialise user service.
        user_service = IUserService.instance(
            service_module="app.service.default_user_service",
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        # Initialise messaging service
        messaging_service = IMessagingService.instance(
            service_module="app.service.default_messaging_service",
            client=client,
            completion_gateway=completion_gateway,
            keyval_storage_gateway=keyval_storage_gateway,
            knowledge_retrieval_gateway=knowledge_retrieval_gateway,
            logging_gateway=logging_gateway,
            platform_gateway=platform_gateway,
            meeting_service=meeting_service,
            user_service=user_service,
        )

        # Initialise IPC service.
        ipc_service = IIPCService.instance(
            service_module="app.service.default_ipc_service",
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            meeting_service=meeting_service,
            user_service=user_service,
        )

        # Load config values into dbm
        load_config(basedir, keyval_storage_gateway)

        # Check login successful.
        if not await login(client, keyval_storage_gateway, logging_gateway):
            os._exit(0)

        # await leave_test_rooms(client)

        # Set profile name if it's not already set.
        profile = await client.get_profile()
        agent_display_name = keyval_storage_gateway.get("matrix_agent_display_name")
        if agent_display_name is not None and profile.displayname != agent_display_name:
            await client.set_displayname(agent_display_name)

        # Register callbacks.
        callbacks = Callbacks(
            client,
            ipc_service,
            keyval_storage_gateway,
            logging_gateway,
            messaging_service,
            user_service,
        )

        client.set_ipc_callback(callbacks.ipc_handler)

        client.add_event_callback(callbacks.invite_alias_event, InviteAliasEvent)
        client.add_event_callback(callbacks.invite_member_event, InviteMemberEvent)
        client.add_event_callback(callbacks.invite_name_event, InviteNameEvent)

        client.add_event_callback(callbacks.room_message_text, RoomMessageText)

        client.add_event_callback(callbacks.room_create_event, RoomCreateEvent)

        client.add_response_callback(callbacks.sync_response, SyncResponse)

        await client.sync_forever(
            1000,
            since=keyval_storage_gateway.get(SYNC_KEY),
            full_state=True,
            set_presence="online",
        )
