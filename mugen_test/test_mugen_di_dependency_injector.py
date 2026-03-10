"""Provides unit tests for mugen.core.di.injector.DependencyInjector."""

from types import SimpleNamespace
import unittest

from mugen.core import di
from mugen.core.contract.client.line import ILineClient
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.signal import ISignalClient
from mugen.core.contract.client.telegram import ITelegramClient
from mugen.core.contract.client.wechat import IWeChatClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.context import IContextEngine
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.email import IEmailGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.sms import ISMSGateway
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
        self.assertIsNone(injector.email_gateway)
        self.assertIsNone(injector.sms_gateway)
        self.assertIsNone(injector.ipc_service)
        self.assertIsNone(injector.keyval_storage_gateway)
        self.assertIsNone(injector.media_storage_gateway)
        self.assertIsNone(injector.relational_storage_gateway)
        self.assertIsNone(injector.web_runtime_store)
        self.assertIsNone(injector.nlp_service)
        self.assertIsNone(injector.platform_service)
        self.assertIsNone(injector.user_service)
        self.assertIsNone(injector.context_engine_service)
        self.assertIsNone(injector.planning_engine_service)
        self.assertIsNone(injector.evaluation_engine_service)
        self.assertIsNone(injector.agent_executor_service)
        self.assertIsNone(injector.plan_run_store_service)
        self.assertIsNone(injector.agent_runtime_service)
        self.assertIsNone(injector.messaging_service)
        self.assertIsNone(injector.knowledge_gateway)
        self.assertIsNone(injector.matrix_client)
        self.assertIsNone(injector.line_client)
        self.assertIsNone(injector.signal_client)
        self.assertIsNone(injector.telegram_client)
        self.assertIsNone(injector.wechat_client)
        self.assertIsNone(injector.whatsapp_client)
        self.assertIsNone(injector.web_client)

    def test_agent_runtime_properties_round_trip(self):
        """Agent-runtime DI slots should support explicit getter/setter access."""

        injector = di.injector.DependencyInjector()
        email_gateway = object()
        sms_gateway = object()
        ipc_service = object()
        keyval_storage_gateway = object()
        ingress_service = object()
        nlp_service = object()
        platform_service = object()
        planning_engine = object()
        evaluation_engine = object()
        agent_executor = object()
        plan_run_store = object()
        agent_runtime = object()
        matrix_client = object()
        telegram_client = object()
        wechat_client = object()
        whatsapp_client = object()
        web_client = object()

        injector.email_gateway = email_gateway
        injector.sms_gateway = sms_gateway
        injector.ipc_service = ipc_service
        injector.keyval_storage_gateway = keyval_storage_gateway
        injector.ingress_service = ingress_service
        injector.nlp_service = nlp_service
        injector.platform_service = platform_service
        injector.planning_engine_service = planning_engine
        injector.evaluation_engine_service = evaluation_engine
        injector.agent_executor_service = agent_executor
        injector.plan_run_store_service = plan_run_store
        injector.agent_runtime_service = agent_runtime
        injector.matrix_client = matrix_client
        injector.telegram_client = telegram_client
        injector.wechat_client = wechat_client
        injector.whatsapp_client = whatsapp_client
        injector.web_client = web_client

        self.assertIs(injector.email_gateway, email_gateway)
        self.assertIs(injector.sms_gateway, sms_gateway)
        self.assertIs(injector.ipc_service, ipc_service)
        self.assertIs(injector.keyval_storage_gateway, keyval_storage_gateway)
        self.assertIs(injector.ingress_service, ingress_service)
        self.assertIs(injector.nlp_service, nlp_service)
        self.assertIs(injector.platform_service, platform_service)
        self.assertIs(injector.planning_engine_service, planning_engine)
        self.assertIs(injector.evaluation_engine_service, evaluation_engine)
        self.assertIs(injector.agent_executor_service, agent_executor)
        self.assertIs(injector.plan_run_store_service, plan_run_store)
        self.assertIs(injector.agent_runtime_service, agent_runtime)
        self.assertIs(injector.matrix_client, matrix_client)
        self.assertIs(injector.telegram_client, telegram_client)
        self.assertIs(injector.wechat_client, wechat_client)
        self.assertIs(injector.whatsapp_client, whatsapp_client)
        self.assertIs(injector.web_client, web_client)

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

            async def check_readiness(self):
                pass

            async def aclose(self):
                pass

            async def get_completion(self, request):
                pass

        completion_gateway = DummyCompletionGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # Email Gateway
        # pylint: disable=too-few-public-methods
        class DummyEmailGatewayClass(IEmailGateway):
            """Dummy email class."""

            def __init__(self, config, logging_gateway):
                pass

            async def check_readiness(self):
                pass

            async def send_email(self, request):
                pass

        email_gateway = DummyEmailGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # SMS Gateway
        # pylint: disable=too-few-public-methods
        class DummySMSGatewayClass(ISMSGateway):
            """Dummy SMS class."""

            def __init__(self, config, logging_gateway):
                pass

            async def check_readiness(self):
                pass

            async def send_sms(self, request):
                pass

        sms_gateway = DummySMSGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # IPC Service
        # pylint: disable=too-few-public-methods
        class DummyIPCServiceClass(IIPCService):
            """Dummy IPC class."""

            def __init__(self, config, logging_gateway):
                pass

            def bind_ipc_extension(self, ext, *, critical: bool = False):
                _ = critical
                pass

            async def handle_ipc_request(self, request):
                pass

        ipc_service = DummyIPCServiceClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # Key-Value Storage Gateway
        class DummyKeyValStorageGatewayClass(IKeyValStorageGateway):
            """Dummy key-value storage class."""

            def __init__(self, config, logging_gateway):
                pass

            async def aclose(self):
                pass

            async def check_readiness(self):
                pass

            async def get_entry(
                self,
                key,
                *,
                namespace=None,
                include_expired=False,
            ):
                pass

            async def put_bytes(
                self,
                key,
                value,
                *,
                namespace=None,
                codec="bytes",
                expected_row_version=None,
                ttl_seconds=None,
            ):
                pass

            async def delete(
                self,
                key,
                *,
                namespace=None,
                expected_row_version=None,
            ):
                pass

            async def exists(self, key, *, namespace=None):
                pass

            async def list_keys(
                self,
                *,
                prefix="",
                namespace=None,
                limit=None,
                cursor=None,
            ):
                pass

            async def compare_and_set(
                self,
                key,
                value,
                *,
                namespace=None,
                codec="bytes",
                expected_row_version=0,
                ttl_seconds=None,
            ):
                pass

        keyval_storage_gateway = DummyKeyValStorageGatewayClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        relational_storage_gateway = object()

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

            async def add_known_user(self, user_id, displayname, room_id):
                pass

            async def get_known_users_list(self):
                pass

            async def get_user_display_name(self, user_id):
                pass

            async def save_known_users_list(self, known_users):
                pass

        user_service = DummyUserServiceClass(
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        class DummyContextEngineClass(IContextEngine):
            """Dummy context engine class."""

            def __init__(self, config, logging_gateway):
                _ = (config, logging_gateway)

            async def prepare_turn(self, request):
                _ = request
                pass

            async def commit_turn(
                self,
                request,
                prepared,
                completion,
                final_user_responses,
                outcome,
            ):
                _ = (
                    request,
                    prepared,
                    completion,
                    final_user_responses,
                    outcome,
                )
                pass

        context_engine_service = DummyContextEngineClass(
            config=config,
            logging_gateway=logging_gateway,
        )

        # Messaging Service
        class DummyMessagingServiceClass(IMessagingService):
            """Dummy messaging class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                completion_gateway,
                context_engine_service,
                logging_gateway,
                user_service,
            ):
                _ = (
                    config,
                    completion_gateway,
                    context_engine_service,
                    logging_gateway,
                    user_service,
                )

            @property
            def cp_extensions(self):
                pass

            @property
            def ct_extensions(self):
                pass

            @property
            def mh_extensions(self):
                pass

            @property
            def rpp_extensions(self):
                pass

            async def handle_message(self, request):
                _ = request
                pass

            def bind_cp_extension(self, ext, *, critical: bool = False):
                _ = ext
                _ = critical
                pass

            def bind_ct_extension(self, ext, *, critical: bool = False):
                _ = ext
                _ = critical
                pass

            def bind_mh_extension(self, ext, *, critical: bool = False):
                _ = ext
                _ = critical
                pass

            def bind_rpp_extension(self, ext, *, critical: bool = False):
                _ = ext
                _ = critical
                pass

        messaging_service = DummyMessagingServiceClass(
            config=config,
            completion_gateway=completion_gateway,
            context_engine_service=context_engine_service,
            logging_gateway=logging_gateway,
            user_service=user_service,
        )

        # Knowledge Gateway
        # pylint: disable=too-few-public-methods
        class DummyKnowledgeGatewayClass(IKnowledgeGateway):
            """Dummy knowledge class."""

            def __init__(self, config, logging_gateway, nlp_service):
                pass

            async def check_readiness(self):
                pass

            async def aclose(self):
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
                relational_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    relational_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def __aenter__(self):
                pass

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def close(self):
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

            async def sync_forever(
                self,
                *,
                since=None,
                timeout=100,
                full_state=True,
                set_presence="online",
            ):
                _ = (since, timeout, full_state, set_presence)
                return None

            async def get_profile(self, user_id=None):
                _ = user_id
                return None

            async def set_displayname(self, displayname):
                _ = displayname
                return None

            async def monitor_runtime_health(self):
                return None

        matrix_client = DummyMatrixClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            relational_storage_gateway=relational_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # Line Client
        class DummyLineClientClass(ILineClient):
            """Dummy LINE client class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def reply_messages(
                self,
                *,
                reply_token: str,
                messages: list[dict],
            ) -> dict | None:
                _ = (reply_token, messages)
                return None

            async def push_messages(
                self,
                *,
                to: str,
                messages: list[dict],
            ) -> dict | None:
                _ = (to, messages)
                return None

            async def multicast_messages(
                self,
                *,
                to: list[str],
                messages: list[dict],
            ) -> dict | None:
                _ = (to, messages)
                return None

            async def send_text_message(
                self,
                *,
                recipient: str,
                text: str,
                reply_token: str | None = None,
            ) -> dict | None:
                _ = (recipient, text, reply_token)
                return None

            async def send_image_message(
                self,
                *,
                recipient: str,
                image: dict,
                reply_token: str | None = None,
            ) -> dict | None:
                _ = (recipient, image, reply_token)
                return None

            async def send_audio_message(
                self,
                *,
                recipient: str,
                audio: dict,
                reply_token: str | None = None,
            ) -> dict | None:
                _ = (recipient, audio, reply_token)
                return None

            async def send_video_message(
                self,
                *,
                recipient: str,
                video: dict,
                reply_token: str | None = None,
            ) -> dict | None:
                _ = (recipient, video, reply_token)
                return None

            async def send_file_message(
                self,
                *,
                recipient: str,
                file: dict,
                reply_token: str | None = None,
            ) -> dict | None:
                _ = (recipient, file, reply_token)
                return None

            async def send_raw_message(
                self,
                *,
                op: str,
                payload: dict,
            ) -> dict | None:
                _ = (op, payload)
                return None

            async def download_media(
                self,
                *,
                message_id: str,
            ) -> dict | None:
                _ = message_id
                return None

            async def get_profile(
                self,
                *,
                user_id: str,
            ) -> dict | None:
                _ = user_id
                return None

            async def emit_processing_signal(
                self,
                recipient: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (recipient, state, message_id)
                return True

        line_client = DummyLineClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # Signal Client
        class DummySignalClientClass(ISignalClient):
            """Dummy Signal client class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                if False:
                    yield {}
                return

            async def send_text_message(
                self,
                *,
                recipient: str,
                text: str,
            ) -> dict | None:
                _ = (recipient, text)
                return None

            async def send_media_message(
                self,
                *,
                recipient: str,
                message: str | None = None,
                base64_attachments: list[str] | None = None,
            ) -> dict | None:
                _ = (recipient, message, base64_attachments)
                return None

            async def send_reaction(
                self,
                *,
                recipient: str,
                reaction: str,
                target_author: str,
                timestamp: int,
                remove: bool = False,
            ) -> dict | None:
                _ = (recipient, reaction, target_author, timestamp, remove)
                return None

            async def send_receipt(
                self,
                *,
                recipient: str,
                receipt_type: str,
                timestamp: int,
            ) -> dict | None:
                _ = (recipient, receipt_type, timestamp)
                return None

            async def emit_processing_signal(
                self,
                recipient: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (recipient, state, message_id)
                return True

            async def download_attachment(self, attachment_id: str) -> dict | None:
                _ = attachment_id
                return None

        signal_client = DummySignalClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # Telegram Client
        class DummyTelegramClientClass(ITelegramClient):
            """Dummy Telegram client class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def init(self):
                pass

            async def verify_startup(self) -> bool:
                return True

            async def close(self):
                pass

            async def send_text_message(
                self,
                *,
                chat_id: str,
                text: str,
                reply_markup: dict | None = None,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, text, reply_markup, reply_to_message_id)
                return None

            async def send_audio_message(
                self,
                *,
                chat_id: str,
                audio: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, audio, reply_to_message_id)
                return None

            async def send_file_message(
                self,
                *,
                chat_id: str,
                document: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, document, reply_to_message_id)
                return None

            async def send_image_message(
                self,
                *,
                chat_id: str,
                photo: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, photo, reply_to_message_id)
                return None

            async def send_video_message(
                self,
                *,
                chat_id: str,
                video: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, video, reply_to_message_id)
                return None

            async def answer_callback_query(
                self,
                *,
                callback_query_id: str,
                text: str | None = None,
                show_alert: bool | None = None,
            ) -> dict | None:
                _ = (callback_query_id, text, show_alert)
                return None

            async def emit_processing_signal(
                self,
                chat_id: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (chat_id, state, message_id)
                return True

            async def download_media(self, file_id: str) -> dict | None:
                _ = file_id
                return None

        telegram_client = DummyTelegramClientClass(
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        # WeChat Client
        class DummyWeChatClientClass(IWeChatClient):
            """Dummy WeChat client class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def send_text_message(
                self,
                *,
                recipient: str,
                text: str,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, text, reply_to)
                return None

            async def send_audio_message(
                self,
                *,
                recipient: str,
                audio: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, audio, reply_to)
                return None

            async def send_file_message(
                self,
                *,
                recipient: str,
                file: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, file, reply_to)
                return None

            async def send_image_message(
                self,
                *,
                recipient: str,
                image: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, image, reply_to)
                return None

            async def send_video_message(
                self,
                *,
                recipient: str,
                video: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, video, reply_to)
                return None

            async def send_raw_message(self, *, payload: dict) -> dict | None:
                _ = payload
                return None

            async def upload_media(
                self,
                *,
                file_path: str,
                media_type: str,
            ) -> dict | None:
                _ = (file_path, media_type)
                return None

            async def download_media(
                self,
                *,
                media_id: str,
                mime_type: str | None = None,
            ) -> dict | None:
                _ = (media_id, mime_type)
                return None

            async def emit_processing_signal(
                self,
                recipient: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (recipient, state, message_id)
                return True

        wechat_client = DummyWeChatClientClass(
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

            async def verify_startup(self) -> bool:
                return True

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

            async def emit_processing_signal(
                self,
                recipient: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                return True

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

        # Web Client
        class DummyWebClientClass(IWebClient):
            """Dummy Web client class."""

            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                media_storage_gateway,
                web_runtime_store,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                pass

            async def init(self):
                pass

            async def close(self):
                pass

            async def wait_until_stopped(self):
                pass

            async def enqueue_message(  # pylint: disable=too-many-arguments
                self,
                *,
                auth_user: str,
                conversation_id: str,
                message_type: str,
                text: str | None = None,
                metadata: dict | None = None,
                file_path: str | None = None,
                mime_type: str | None = None,
                original_filename: str | None = None,
                client_message_id: str | None = None,
            ) -> dict:
                pass

            async def stream_events(
                self,
                *,
                auth_user: str,
                conversation_id: str,
                last_event_id: str | None = None,
            ):
                pass

            async def resolve_media_download(
                self,
                *,
                auth_user: str,
                token: str,
            ) -> dict | None:
                pass

        web_client = DummyWebClientClass(
            config=config,
            ipc_service=ipc_service,
            media_storage_gateway=object(),
            web_runtime_store=object(),
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        media_storage_gateway = object()
        relational_storage_gateway = object()
        web_runtime_store = object()

        ## Create injector.
        injector = di.injector.DependencyInjector(
            config=config,
            logging_gateway=logging_gateway,
            completion_gateway=completion_gateway,
            email_gateway=email_gateway,
            sms_gateway=sms_gateway,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            media_storage_gateway=media_storage_gateway,
            relational_storage_gateway=relational_storage_gateway,
            web_runtime_store=web_runtime_store,
            nlp_service=nlp_service,
            platform_service=platform_service,
            user_service=user_service,
            context_engine_service=context_engine_service,
            messaging_service=messaging_service,
            knowledge_gateway=knowledge_gateway,
            matrix_client=matrix_client,
            line_client=line_client,
            signal_client=signal_client,
            telegram_client=telegram_client,
            wechat_client=wechat_client,
            whatsapp_client=whatsapp_client,
            web_client=web_client,
        )

        ## Assertions.
        self.assertEqual(injector.config, config)
        self.assertEqual(injector.logging_gateway, logging_gateway)
        self.assertEqual(injector.completion_gateway, completion_gateway)
        self.assertEqual(injector.email_gateway, email_gateway)
        self.assertEqual(injector.sms_gateway, sms_gateway)
        self.assertEqual(injector.ipc_service, ipc_service)
        self.assertEqual(injector.keyval_storage_gateway, keyval_storage_gateway)
        self.assertEqual(injector.media_storage_gateway, media_storage_gateway)
        self.assertEqual(
            injector.relational_storage_gateway, relational_storage_gateway
        )
        self.assertEqual(injector.web_runtime_store, web_runtime_store)
        self.assertEqual(injector.nlp_service, nlp_service)
        self.assertEqual(injector.platform_service, platform_service)
        self.assertEqual(injector.user_service, user_service)
        self.assertEqual(injector.context_engine_service, context_engine_service)
        self.assertEqual(injector.messaging_service, messaging_service)
        self.assertEqual(injector.knowledge_gateway, knowledge_gateway)
        self.assertEqual(injector.matrix_client, matrix_client)
        self.assertEqual(injector.line_client, line_client)
        self.assertEqual(injector.signal_client, signal_client)
        self.assertEqual(injector.telegram_client, telegram_client)
        self.assertEqual(injector.wechat_client, wechat_client)
        self.assertEqual(injector.whatsapp_client, whatsapp_client)
        self.assertEqual(injector.web_client, web_client)

    def test_setters_cover_runtime_storage_and_web_runtime_store(self):
        injector = di.injector.DependencyInjector()

        media_storage_gateway = object()
        relational_storage_gateway = object()
        relational_runtime = object()
        web_runtime_store = object()

        injector.media_storage_gateway = media_storage_gateway
        injector.relational_storage_gateway = relational_storage_gateway
        injector.relational_runtime = relational_runtime
        injector.web_runtime_store = web_runtime_store

        self.assertIs(injector.media_storage_gateway, media_storage_gateway)
        self.assertIs(injector.relational_storage_gateway, relational_storage_gateway)
        self.assertIs(injector.relational_runtime, relational_runtime)
        self.assertIs(injector.web_runtime_store, web_runtime_store)

    def test_register_get_ext_service_round_trip(self):
        """Test extension service registration and retrieval."""
        injector = di.injector.DependencyInjector()

        service = object()
        injector.register_ext_service("demo", service)

        self.assertIs(injector.get_ext_service("demo"), service)

    def test_line_client_property_round_trip(self):
        """Test line_client property getter/setter."""
        injector = di.injector.DependencyInjector()
        line_client = object()

        injector.line_client = line_client

        self.assertIs(injector.line_client, line_client)

    def test_signal_client_property_round_trip(self):
        """Test signal_client property getter/setter."""
        injector = di.injector.DependencyInjector()
        signal_client = object()

        injector.signal_client = signal_client

        self.assertIs(injector.signal_client, signal_client)

    def test_register_ext_service_duplicate_without_override(self):
        """Test duplicate extension registration without override."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("demo", object())

        with self.assertRaises(KeyError):
            injector.register_ext_service("demo", object())

    def test_register_ext_service_duplicate_with_override(self):
        """Test duplicate extension registration with override."""
        injector = di.injector.DependencyInjector()
        first = object()
        second = object()

        injector.register_ext_service("demo", first)
        injector.register_ext_service("demo", second, override=True)

        self.assertIs(injector.get_ext_service("demo"), second)

    def test_register_ext_services_round_trip(self):
        """Test bulk extension service registration and retrieval."""
        injector = di.injector.DependencyInjector()
        first = object()
        second = object()

        injector.register_ext_services({"one": first, "two": second})

        self.assertIs(injector.get_ext_service("one"), first)
        self.assertIs(injector.get_ext_service("two"), second)

    def test_register_ext_services_non_atomic_is_partial_on_failure(self):
        """Test non-atomic bulk registration can partially apply before failure."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("existing", object())

        with self.assertRaises(KeyError):
            injector.register_ext_services(
                {
                    "new": object(),
                    "existing": object(),
                }
            )

        self.assertTrue(injector.has_ext_service("new"))

    def test_register_ext_services_atomic_rolls_back_on_failure(self):
        """Test atomic bulk registration does not partially apply on failure."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("existing", object())

        with self.assertRaises(KeyError):
            injector.register_ext_services(
                {
                    "new": object(),
                    "existing": object(),
                },
                atomic=True,
            )

        self.assertFalse(injector.has_ext_service("new"))

    def test_register_ext_services_atomic_success(self):
        """Test atomic bulk registration applies all services on success."""
        injector = di.injector.DependencyInjector()
        one = object()
        two = object()

        injector.register_ext_services(
            {
                "one": one,
                "two": two,
            },
            atomic=True,
        )

        self.assertIs(injector.get_ext_service("one"), one)
        self.assertIs(injector.get_ext_service("two"), two)

    def test_register_ext_services_duplicate_without_override(self):
        """Test bulk registration duplicate behavior without override."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("demo", object())

        with self.assertRaises(KeyError):
            injector.register_ext_services({"demo": object()})

    def test_register_ext_services_duplicate_with_override(self):
        """Test bulk registration duplicate behavior with override."""
        injector = di.injector.DependencyInjector()
        first = object()
        second = object()
        injector.register_ext_service("demo", first)

        injector.register_ext_services({"demo": second}, override=True)

        self.assertIs(injector.get_ext_service("demo"), second)

    def test_register_ext_services_requires_mapping(self):
        """Test bulk registration requires a mapping input."""
        injector = di.injector.DependencyInjector()

        with self.assertRaises(TypeError):
            injector.register_ext_services(["demo"])

    def test_get_ext_service_missing_with_default(self):
        """Test retrieving missing extension service with a default."""
        injector = di.injector.DependencyInjector()
        fallback = object()

        self.assertIs(injector.get_ext_service("missing", fallback), fallback)

    def test_get_ext_service_missing_with_none_default(self):
        """Test retrieving missing extension service with explicit None default."""
        injector = di.injector.DependencyInjector()

        self.assertIsNone(injector.get_ext_service("missing", None))

    def test_get_ext_service_missing_without_default(self):
        """Test retrieving missing extension service without default."""
        injector = di.injector.DependencyInjector()

        with self.assertRaises(KeyError):
            injector.get_ext_service("missing")

    def test_get_required_ext_service_round_trip(self):
        """Test get_required_ext_service returns registered service."""
        injector = di.injector.DependencyInjector()
        service = object()
        injector.register_ext_service("demo", service)

        self.assertIs(injector.get_required_ext_service("demo"), service)

    def test_get_required_ext_service_missing(self):
        """Test get_required_ext_service raises for missing service."""
        injector = di.injector.DependencyInjector()

        with self.assertRaises(KeyError):
            injector.get_required_ext_service("missing")

    def test_has_ext_service(self):
        """Test has_ext_service for existing and missing names."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("demo", object())

        self.assertTrue(injector.has_ext_service("demo"))
        self.assertFalse(injector.has_ext_service("missing"))

    def test_ext_services_is_read_only_mapping(self):
        """Test extension services mapping is read-only."""
        injector = di.injector.DependencyInjector()
        injector.register_ext_service("demo", object())

        with self.assertRaises(TypeError):
            injector.ext_services["x"] = object()

    def test_ext_service_name_validation(self):
        """Test extension service name validation."""
        injector = di.injector.DependencyInjector()

        with self.assertRaises(ValueError):
            injector.register_ext_service("", object())

        with self.assertRaises(ValueError):
            injector.register_ext_service("   ", object())

        with self.assertRaises(ValueError):
            injector.register_ext_services({"": object()})

        with self.assertRaises(ValueError):
            injector.get_ext_service("")

        with self.assertRaises(ValueError):
            injector.get_required_ext_service("   ")

        with self.assertRaises(ValueError):
            injector.has_ext_service("")

    def test_knowledge_gateway_setter_assignment(self):
        """Test knowledge_gateway setter path after initialization."""
        injector = di.injector.DependencyInjector()
        gateway = object()

        injector.knowledge_gateway = gateway

        self.assertIs(injector.knowledge_gateway, gateway)

    def test_sms_gateway_setter_assignment(self):
        """Test sms_gateway setter path after initialization."""
        injector = di.injector.DependencyInjector()
        gateway = object()

        injector.sms_gateway = gateway

        self.assertIs(injector.sms_gateway, gateway)
