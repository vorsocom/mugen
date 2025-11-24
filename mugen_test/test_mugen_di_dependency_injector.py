"""Provides unit tests for mugen.core.di.injector.DependencyInjector."""

from types import SimpleNamespace
import unittest

from mugen.core import di
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.nlp import INLPService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.contract.service.user import IUserService


class TestDependencyInjector(unittest.TestCase):
    """Unit tests for mugen.core.di.injector.DependencyInjector."""

    def test_no_init_parameters(self):
        """Test instantiation without parameters."""

        injector = di.injector.DependencyInjector()

        self.assertIsNone(injector.config)
        self.assertIsNone(injector.logging_gateway)
        self.assertIsNone(injector.completion_gateway)
        self.assertIsNone(injector.ipc_service)
        self.assertIsNone(injector.keyval_storage_gateway)
        self.assertIsNone(injector.nlp_service)
        self.assertIsNone(injector.platform_service)
        self.assertIsNone(injector.user_service)
        self.assertIsNone(injector.messaging_service)
        self.assertIsNone(injector.knowledge_gateway)
        self.assertIsNone(injector.matrix_client)
        self.assertIsNone(injector.telnet_client)
        self.assertIsNone(injector.whatsapp_client)

    def test_with_init_parameters(self):
        """Test instantiation with all parameters."""

        # Config
        config = SimpleNamespace()

        # Logging Gateway
        class DummyLoggingGatewayClass(ILoggingGateway):
            """Dummy logging class."""

            def __init__(self, config: dict):
                pass

            def critical(self, message):
                pass

            def debug(self, message):
                pass

            def error(self, message):
                pass

            def info(self, message):
                pass

            def warning(self, message):
                pass

        logging_gateway = DummyLoggingGatewayClass(config)

        # Completion Gateway
        # pylint: disable=too-few-public-methods
        class DummyCompletionGatewayClass(ICompletionGateway):
            """Dummy completion class."""

            def __init__(self, config, logging_gateway):
                pass

            async def get_completion(self, context, operation="completion"):
                pass

        completion_gateway = DummyCompletionGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # IPC Service
        # pylint: disable=too-few-public-methods
        class DummyIPCServiceClass(IIPCService):
            """Dummy IPC class."""

            def __init__(self, logging_gateway):
                pass

            def register_ipc_extension(self, ext):
                pass

            async def handle_ipc_request(self, platform, ipc_payload):
                pass

        ipc_service = DummyIPCServiceClass(logging_gateway=logging_gateway)

        # Key-Value Storage Gateway
        class DummyKeyValStorageGatewayClass(IKeyValStorageGateway):
            """Dummy key-value storage class."""

            def __init__(self, config, logging_gateway):
                pass

            def close(self):
                pass

            def get(self, key, decode=True):
                pass

            def has_key(self, key):
                pass

            def keys(self):
                pass

            def put(self, key, value):
                pass

            def remove(self, key):
                pass

        keyval_storage_gateway = DummyKeyValStorageGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # NLP Service
        # pylint: disable=too-few-public-methods
        class DummyNLPServiceClass(INLPService):
            """Dummy NLP class."""

            def __init__(self, logging_gateway):
                pass

            def get_keywords(self, text):
                pass

        nlp_service = DummyNLPServiceClass(logging_gateway=logging_gateway)

        # Platform Service
        class DummyPlatformServiceClass(IPlatformService):
            """Dummy platform class."""

            def __init__(self, config, logging_gateway):
                pass

            @property
            def active_platforms(self):
                pass

            def extension_supported(self, ext):
                pass

        platform_service = DummyPlatformServiceClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # User Service
        class DummyUserServiceClass(IUserService):
            """Dummy user class."""

            def __init__(self, keyval_storage_gateway, logging_gateway):
                pass

            def add_known_user(self, user_id, displayname, room_id):
                pass

            def get_known_users_list(self):
                pass

            def get_user_display_name(self, user_id):
                pass

            def save_known_users_list(self, known_users):
                pass

        user_service = DummyUserServiceClass(
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        # Messaging Service
        class DummyMessagingServiceClass(IMessagingService):
            """Dummy messaging class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                completion_gateway,
                keyval_storage_gateway,
                logging_gateway,
                user_service,
            ):
                pass

            @property
            def cp_extensions(self):
                pass

            @property
            def ct_extensions(self):
                pass

            @property
            def ctx_extensions(self):
                pass

            @property
            def mh_extensions(self):
                pass

            @property
            def rag_extensions(self):
                pass

            @property
            def rpp_extensions(self):
                pass

            async def handle_audio_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict,
            ) -> list[dict] | None:
                pass

            async def handle_file_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict,
            ) -> list[dict] | None:
                pass

            async def handle_image_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict,
            ) -> list[dict] | None:
                pass

            async def handle_text_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: str,
                message_context: list[str] = None,
            ):
                pass

            async def handle_video_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict,
            ) -> list[dict] | None:
                pass

            def register_cp_extension(self, ext):
                pass

            def register_ct_extension(self, ext):
                pass

            def register_ctx_extension(self, ext):
                pass

            def register_mh_extension(self, ext):
                pass

            def register_rag_extension(self, ext):
                pass

            def register_rpp_extension(self, ext):
                pass

        messaging_service = DummyMessagingServiceClass(
            config=config,
            completion_gateway=completion_gateway,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            user_service=user_service,
        )

        # Knowledge Gateway
        # pylint: disable=too-few-public-methods
        class DummyKnowledgeGatewayClass(IKnowledgeGateway):
            """Dummy knowledge class."""

            def __init__(self, config, logging_gateway, nlp_service):
                pass

            async def search(  # pylint: disable=too-many-arguments
                self,
                params,
            ):
                pass

        knowledge_gateway = DummyKnowledgeGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
            nlp_service=nlp_service,
        )

        # Matrix Client
        class DummyMatrixClientClass(IMatrixClient):
            """Dummy Matrix class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                pass

            async def __aenter__(self):
                pass

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            @property
            def sync_token(self):
                pass

            def cleanup_known_user_devices_list(self):
                pass

            def trust_known_user_devices(self):
                pass

            def verify_user_devices(self, user_id):
                pass

        matrix_client = DummyMatrixClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # Telnet Client
        class DummyTelnetClientClass(ITelnetClient):
            """Dummy Telnet class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                pass

            async def __aenter__(self):
                pass

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def start_server(self):
                pass

        telnet_client = DummyTelnetClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # WhatsApp Client
        class DummyWhatsAppClientClass(IWhatsAppClient):
            """Dummy WhatsApp class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                pass

            async def __aenter__(self):
                pass

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def init(self):
                pass

            async def close(self):
                pass

            async def delete_media(self, media_id: str):
                pass

            async def download_media(self, media_url: str, mimetype: str):
                pass

            async def retrieve_media_url(self, media_id: str):
                pass

            async def send_audio_message(
                self,
                audio: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_contacts_message(
                self,
                contacts: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_document_message(
                self,
                document: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_image_message(
                self,
                image: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_interactive_message(
                self,
                interactive: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_location_message(
                self,
                location: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_reaction_message(
                self, reaction: dict, recipient: str
            ) -> str | None:
                pass

            async def send_sticker_message(
                self,
                sticker: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_template_message(
                self,
                template: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_text_message(
                self,
                message: str,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def send_video_message(
                self,
                video: dict,
                recipient: str,
                reply_to: str = None,
            ):
                pass

            async def upload_media(
                self,
                file_path: str,
                file_type: str,
            ):
                pass

        whatsapp_client = DummyWhatsAppClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        ## Create injector.
        injector = di.injector.DependencyInjector(
            config=config,
            logging_gateway=logging_gateway,
            completion_gateway=completion_gateway,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            nlp_service=nlp_service,
            platform_service=platform_service,
            user_service=user_service,
            messaging_service=messaging_service,
            knowledge_gateway=knowledge_gateway,
            matrix_client=matrix_client,
            telnet_client=telnet_client,
            whatsapp_client=whatsapp_client,
        )

        ## Assertions.
        self.assertEqual(injector.config, config)
        self.assertEqual(injector.logging_gateway, logging_gateway)
        self.assertEqual(injector.completion_gateway, completion_gateway)
        self.assertEqual(injector.ipc_service, ipc_service)
        self.assertEqual(injector.keyval_storage_gateway, keyval_storage_gateway)
        self.assertEqual(injector.nlp_service, nlp_service)
        self.assertEqual(injector.platform_service, platform_service)
        self.assertEqual(injector.user_service, user_service)
        self.assertEqual(injector.messaging_service, messaging_service)
        self.assertEqual(injector.knowledge_gateway, knowledge_gateway)
        self.assertEqual(injector.matrix_client, matrix_client)
        self.assertEqual(injector.telnet_client, telnet_client)
        self.assertEqual(injector.whatsapp_client, whatsapp_client)
