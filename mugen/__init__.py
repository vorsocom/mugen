"""Quart application package."""

__all__ = [
    "BootstrapConfigError",
    "BootstrapError",
    "ExtensionLoadError",
    "bootstrap_app",
    "create_quart_app",
    "run_clients",
    "run_platform_clients",
]

import asyncio
from importlib import import_module
import random
import re
from time import perf_counter
from types import SimpleNamespace

from quart import Quart

from mugen.config import AppConfig
from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.platform import IPlatformService


class BootstrapError(RuntimeError):
    """Base error type for application bootstrap failures."""


class BootstrapConfigError(BootstrapError):
    """Raised when bootstrap configuration is invalid."""


class ExtensionLoadError(BootstrapError):
    """Raised when an extension cannot be loaded or initialized."""


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _whatsapp_provider():
    return di.container.whatsapp_client


def _keyval_storage_gateway_provider():
    return di.container.keyval_storage_gateway


def _ipc_provider():
    return di.container.ipc_service


def _messaging_provider():
    return di.container.messaging_service


def _platform_provider():
    return di.container.platform_service


def _telnet_provider():
    return di.container.telnet_client


def _matrix_provider():
    return di.container.matrix_client


def _extension_enabled(ext: SimpleNamespace) -> bool:
    """Resolve whether an extension is enabled by configuration."""
    raw_enabled = getattr(ext, "enabled", True)
    if isinstance(raw_enabled, str):
        normalized = raw_enabled.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(raw_enabled)


def _split_extension_path(path: str) -> tuple[str, str | None]:
    """Split extension path into module and optional class target."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Extension path must be a non-empty string.")

    normalized = path.strip()
    if ":" not in normalized:
        return normalized, None

    module_name, class_name = normalized.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("Extension path must use module:ClassName.")

    return module_name, class_name


def _resolve_extension_class(
    *,
    interface: type,
    module_name: str,
    class_name: str | None,
    ext_path: str,
) -> type:
    """Resolve extension class deterministically for the configured path."""
    if class_name is not None:
        module = import_module(name=module_name)
        ext_class = getattr(module, class_name, None)
        if not isinstance(ext_class, type):
            raise ExtensionLoadError(f"Extension class not found: {ext_path}.")
        if not issubclass(ext_class, interface):
            raise ExtensionLoadError(
                f"Extension class is not a valid {interface.__name__}: {ext_path}."
            )
        return ext_class

    module_matches = [x for x in interface.__subclasses__() if x.__module__ == module_name]
    if not module_matches:
        raise ExtensionLoadError(
            f"Extension is not a subclass of its intended type: {ext_path}."
        )

    if len(module_matches) > 1:
        candidates = ", ".join(
            sorted(x.__qualname__ for x in module_matches)
        )
        raise ExtensionLoadError(
            "Multiple extension classes found. "
            f"Use module:ClassName for deterministic resolution ({ext_path}). "
            f"Candidates: {candidates}."
        )

    return module_matches[0]


def create_quart_app(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
) -> Quart:
    """Application factory."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()

    # Create new Quart application.
    app = Quart(__name__)

    # Check for valid configuration name.
    try:
        environment = config.mugen.environment
    except AttributeError as exc:
        logger.error("Configuration unavailable.")
        raise BootstrapConfigError("Configuration unavailable.") from exc

    logger.debug(f"Configured environment: {environment}.")
    if environment not in (
        "default",
        "development",
        "testing",
        "production",
    ):
        logger.error("Invalid environment name.")
        raise BootstrapConfigError("Invalid environment name.")

    # Create application configuration object.
    app.config.from_object(AppConfig[environment])

    # Initialize application.
    AppConfig[environment].init_app(app, config)

    # Return the built application object.
    return app


# pylint: disable=too-many-branches
# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
async def run_clients(
    app: Quart,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
) -> None:
    """Entrypoint for assistants."""
    await bootstrap_app(app, config_provider=config_provider)
    await run_platform_clients(
        app,
        config_provider=config_provider,
        logger_provider=logger_provider,
        whatsapp_provider=whatsapp_provider,
    )


async def bootstrap_app(
    app: Quart,
    config_provider=_config_provider,
) -> None:
    """Phase A bootstrap for app extensions and API registration."""
    # Discover and register core plugins and
    # third-party extensions.
    await register_extensions(app, config_provider=config_provider)

    # Register blueprints after extensions have been loaded.
    # This allows extensions to hack the api.
    app.register_blueprint(api, url_prefix="/api")


async def run_platform_clients(
    app: Quart,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
    keyval_storage_gateway_provider=_keyval_storage_gateway_provider,
) -> None:
    """Phase B bootstrap for long-running platform clients."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    whatsapp_client: IWhatsAppClient = whatsapp_provider()
    keyval_storage_gateway: IKeyValStorageGateway = keyval_storage_gateway_provider()

    try:
        # Do platform checks.
        tasks = []

        try:
            if "matrix" in config.mugen.platforms:
                logger.debug("Running matrix client.")
                # Create task to run Matrix client.
                tasks.append(asyncio.create_task(run_matrix_client()))

            if "telnet" in config.mugen.platforms:
                logger.debug("Running telnet client.")
                # Create task to run Telnet client.
                tasks.append(asyncio.create_task(run_telnet_client()))

            if "whatsapp" in config.mugen.platforms:
                logger.debug("Running whatsapp client.")
                # Create task to run WhatsApp client.
                tasks.append(asyncio.create_task(run_whatsapp_client()))
        except AttributeError as exc:
            logger.error("Invalid platform configuration.")
            raise BootstrapConfigError("Invalid platform configuration.") from exc

        try:
            await asyncio.gather(*tasks)
        except asyncio.exceptions.CancelledError:
            if whatsapp_client is not None:
                logger.debug("Closing whatsapp client.")
                try:
                    await whatsapp_client.close()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning(f"Failed to close whatsapp client ({exc}).")
    finally:
        if keyval_storage_gateway is not None:
            logger.debug("Closing keyval storage gateway.")
            try:
                keyval_storage_gateway.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Failed to close keyval storage gateway ({exc}).")


async def register_extensions(  # pylint: disable=too-many-positional-arguments
    app: Quart,
    config_provider=_config_provider,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
    messaging_provider=_messaging_provider,
    platform_provider=_platform_provider,
) -> None:
    """Register core plugins and third party extensions."""
    config: SimpleNamespace = config_provider()
    ipc_service: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()
    messaging_service: IMessagingService = messaging_provider()
    platform_service: IPlatformService = platform_provider()

    # Load extensions if specified. These include:
    # 1. Command Processor (CP) extensions.
    # 2. Conversational Trigger (CT) extensions.
    # 3. Context (CTX) extensions.
    # 4. Framework (FW) extensions.
    # 5. Inter-Process Communication (IPC) extensions.
    # 6. Message Handler (MH) extensions.
    # 7. Retrieval Augmented Generation (RAG) extensions.
    # 8. Response Pre-Processor (RPP) extensions.
    extensions = []
    sweep_started_at = perf_counter()

    try:
        # Load core plugins.
        if hasattr(config.mugen.modules.core, "plugins"):
            logger.debug("Adding plugins for loading.")
            extensions += config.mugen.modules.core.plugins
    except AttributeError:
        logger.error("Plugin configuration attribute error.")

    try:
        # Load third party extensions.
        if hasattr(config.mugen.modules, "extensions"):
            logger.debug("Adding extensions for loading.")
            extensions += config.mugen.modules.extensions
    except AttributeError:
        logger.error("Extension configuration attribute error.")

    # Register core plugins and third party extensions.
    for ext in extensions:
        ext_started_at = perf_counter()
        ext_type = getattr(ext, "type", "<unknown>")
        ext_path = getattr(ext, "path", "<unknown>")
        if not _extension_enabled(ext):
            logger.info(f"Skipping disabled extension: {ext_path} ({ext_type}).")
            continue

        try:
            ext_module_name, ext_class_name = _split_extension_path(ext_path)
        except ValueError as exc:
            logger.error("Invalid extension path format.")
            logger.info(f"Module: {ext_path}.")
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(
                f"Invalid extension path format: {ext_path}."
            ) from exc

        # Flag used to signal that the plugin/extension
        # registration was successful.
        registered = False

        # Flag used to signal that the plugin/extension
        # platform is unsupported.
        extension_supported = False

        # Try importing the plugin/extension module.
        try:
            import_module(name=ext_module_name)
        except ModuleNotFoundError as exc:
            logger.error("Module import failed.")
            logger.info(f"Module: {ext_module_name}.")
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(f"Module import failed: {ext_module_name}.") from exc

        try:
            if ext_type == "cp":
                cp_ext_class = _resolve_extension_class(
                    interface=ICPExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                cp_ext = cp_ext_class()
                extension_supported = platform_service.extension_supported(cp_ext)
                if extension_supported:
                    messaging_service.register_cp_extension(cp_ext)
                    registered = True
            elif ext_type == "ct":
                ct_ext_class = _resolve_extension_class(
                    interface=ICTExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ct_ext = ct_ext_class()
                extension_supported = platform_service.extension_supported(ct_ext)
                if extension_supported:
                    messaging_service.register_ct_extension(ct_ext)
                    registered = True
            elif ext_type == "ctx":
                ctx_ext_class = _resolve_extension_class(
                    interface=ICTXExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ctx_ext = ctx_ext_class()
                extension_supported = platform_service.extension_supported(ctx_ext)
                if extension_supported:
                    messaging_service.register_ctx_extension(ctx_ext)
                    registered = True
            elif ext_type == "fw":
                fw_ext_class = _resolve_extension_class(
                    interface=IFWExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                fw_ext = fw_ext_class()
                extension_supported = platform_service.extension_supported(fw_ext)
                if extension_supported:
                    await fw_ext.setup(app)
                    registered = True
            elif ext_type == "ipc":
                ipc_ext_class = _resolve_extension_class(
                    interface=IIPCExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ipc_ext = ipc_ext_class()
                extension_supported = platform_service.extension_supported(ipc_ext)
                if extension_supported:
                    ipc_service.register_ipc_extension(ipc_ext)
                    registered = True
            elif ext_type == "mh":
                mh_ext_class = _resolve_extension_class(
                    interface=IMHExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                mh_ext = mh_ext_class()
                extension_supported = platform_service.extension_supported(mh_ext)
                if extension_supported:
                    messaging_service.register_mh_extension(mh_ext)
                    registered = True
            elif ext_type == "rag":
                rag_ext_class = _resolve_extension_class(
                    interface=IRAGExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                rag_ext = rag_ext_class()
                extension_supported = platform_service.extension_supported(rag_ext)
                if extension_supported:
                    messaging_service.register_rag_extension(rag_ext)
                    registered = True
            elif ext_type == "rpp":
                rpp_ext_class = _resolve_extension_class(
                    interface=IRPPExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                rpp_ext = rpp_ext_class()
                extension_supported = platform_service.extension_supported(rpp_ext)
                if extension_supported:
                    messaging_service.register_rpp_extension(rpp_ext)
                    registered = True
            else:
                logger.warning(f"Unknown extension type: {ext_type}.")
        except TypeError as exc:
            logger.exception(
                "Incomplete subclass implementation for extension: %s.",
                ext_path,
            )
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(
                f"Incomplete subclass implementation for extension: {ext_path}."
            ) from exc
        except ExtensionLoadError:
            logger.exception("Extension class resolution failed: %s.", ext_path)
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise

        if not extension_supported:
            logger.warning(f"Extension not supported by active platforms: {ext_path}.")

        if registered:
            logger.debug(f"Registered {ext_type.upper()} extension: {ext_path}.")

        logger.debug(
            "Extension bootstrap completed"
            f" type={ext_type} path={ext_path}"
            f" supported={extension_supported} registered={registered}"
            f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
        )

    logger.debug(
        "Extension bootstrap sweep completed"
        f" total_extensions={len(extensions)}"
        f" elapsed_seconds={perf_counter() - sweep_started_at:.3f}"
    )


async def run_telnet_client(
    logger_provider=_logger_provider,
    telnet_provider=_telnet_provider,
) -> None:
    """Run assistant for Telnet server."""
    logger: ILoggingGateway = logger_provider()
    telnet_client: ITelnetClient = telnet_provider()

    async with telnet_client as client:
        try:
            await asyncio.create_task(client.start_server())
            logger.debug("Telnet client started.")
        except asyncio.exceptions.CancelledError:
            logger.error("Telnet client shutting down.")


async def run_matrix_client(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    matrix_provider=_matrix_provider,
) -> None:
    """Run assistant for the Matrix platform."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    matrix_client: IMatrixClient = matrix_provider()
    max_sync_retries = 5
    backoff_base_seconds = 1.0
    backoff_max_seconds = 30.0
    backoff_jitter_seconds = 0.25

    # Initialise matrix client.
    async with matrix_client as client:
        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_first_sync():

            # Wait for first sync to complete.
            await client.synced.wait()

            # Set profile name if it's not already set.
            profile = await client.get_profile()
            assistant_display_name = config.matrix.assistant.name
            if (
                assistant_display_name is not None
                and profile.displayname != assistant_display_name
            ):
                await client.set_displayname(assistant_display_name)

            # Cleanup device list and trust known devices.
            # matrix_client.cleanup_known_user_devices_list()
            client.trust_known_user_devices()

        retry_attempt = 0
        while True:
            try:
                # Start process loop.
                await asyncio.gather(
                    asyncio.create_task(wait_on_first_sync()),
                    asyncio.create_task(
                        client.sync_forever(
                            since=client.sync_token,
                            timeout=100,
                            full_state=True,
                            set_presence="online",
                        )
                    ),
                    return_exceptions=False,
                )
                logger.debug("Matrix client started.")
                return
            except asyncio.exceptions.CancelledError:
                logger.error("Matrix client shutting down.")
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                is_auth_failure = (
                    re.search(
                        r"(m_unknown_token|unauthorized|forbidden|invalid token|access token)",
                        str(exc).lower(),
                    )
                    is not None
                )
                if is_auth_failure:
                    logger.error("Matrix client authentication failed; shutting down.")
                    return

                if retry_attempt >= max_sync_retries:
                    logger.error("Matrix client sync failed after max retries.")
                    return

                delay_seconds = min(
                    backoff_max_seconds,
                    (backoff_base_seconds * (2**retry_attempt))
                    + random.uniform(0, backoff_jitter_seconds),
                )
                logger.warning(
                    "Matrix client sync error; retrying."
                    f" attempt={retry_attempt + 1}/{max_sync_retries}"
                    f" delay_seconds={delay_seconds:.2f}"
                    f" error={type(exc).__name__}: {exc}"
                )
                retry_attempt += 1
                await asyncio.sleep(delay_seconds)


async def run_whatsapp_client(
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
) -> None:
    """Run assistant for the whatsapp platform."""
    logger: ILoggingGateway = logger_provider()
    whatsapp_client: IWhatsAppClient = whatsapp_provider()

    await asyncio.gather(asyncio.create_task(whatsapp_client.init()))
    logger.debug("WhatsApp client started.")
