"""Quart application package."""

__all__ = ["create_quart_app", "run_clients"]

import asyncio
from importlib import import_module
import sys
from types import SimpleNamespace

from quart import Quart

from mugen.config import AppConfig
from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway


def create_quart_app(
    config: SimpleNamespace = di.container.config,
    logger: ILoggingGateway = di.container.logging_gateway,
) -> Quart:
    """Application factory."""
    # Create new Quart application.
    app = Quart(__name__)

    # Check for valid configuration name.
    try:
        environment = config.mugen.environment
    except AttributeError:
        logger.error("Configuration unavailable.")
        sys.exit(1)

    logger.debug(f"Configured environment: {environment}.")
    if environment not in (
        "default",
        "development",
        "testing",
        "production",
    ):
        logger.error("Invalid environment name.")
        sys.exit(1)

    # Create application configuration object.
    app.config.from_object(AppConfig[environment])

    # Initialize application.
    AppConfig[environment].init_app(app)

    # Return the built application object.
    return app


# pylint: disable=too-many-branches
# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
async def run_clients(
    app: Quart,
    config: SimpleNamespace = di.container.config,
    logger=di.container.logging_gateway,
    whatsapp_client: IWhatsAppClient = di.container.whatsapp_client,
) -> None:
    """Entrypoint for assistants."""
    # Discover and register core plugins and
    # third-party extensions.
    await register_extensions()

    # Register blueprints after extensions have been loaded.
    # This allows extensions to hack the api.
    app.register_blueprint(api, url_prefix="/api")

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
    except AttributeError:
        logger.error("Invalid platform configuration.")
        sys.exit(1)

    try:
        await asyncio.gather(*tasks)
    except asyncio.exceptions.CancelledError:
        if whatsapp_client is not None:
            logger.debug("Closing whatsapp client.")
            await whatsapp_client.close()


async def register_extensions(
    config: SimpleNamespace = di.container.config,
    ipc_service=di.container.ipc_service,
    logger=di.container.logging_gateway,
    messaging_service=di.container.messaging_service,
    platform_service=di.container.platform_service,
) -> None:
    """Register core plugins and third party extensions."""

    # Load extensions if specified. These include:
    # 1. Conversational Trigger (CT) extensions.
    # 2. Context (CTX) extensions.
    # 3. Framework (FW) extensions.
    # 4. Inter-Process Communication (IPC) extensions.
    # 5. Message Handler (MH) extensions.
    # 6. Retrieval Augmented Generation (RAG) extensions.
    # 7. Response Pre-Processor (RPP) extensions.
    extensions = []

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
        # Flag used to signal that the plugin/extension
        # registration was successful.
        registered = False

        # Flag used to signal that the plugin/extension
        # platform is unsupported.
        extension_supported = False

        # Try importing the plugin/extension module.
        try:
            import_module(name=ext.path)
        except ModuleNotFoundError:
            logger.error("Module import failed.")
            logger.info(f"Module: {ext.path}.")
            sys.exit(1)

        try:
            try:
                if ext.type == "ct":
                    ct_ext_class = [
                        x
                        for x in ICTExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    ct_ext = ct_ext_class()
                    extension_supported = platform_service.extension_supported(ct_ext)
                    if extension_supported:
                        messaging_service.register_ct_extension(ct_ext)
                        registered = True
                elif ext.type == "ctx":
                    ctx_ext_class = [
                        x
                        for x in ICTXExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    ctx_ext = ctx_ext_class()
                    extension_supported = platform_service.extension_supported(ctx_ext)
                    if extension_supported:
                        messaging_service.register_ctx_extension(ctx_ext)
                        registered = True
                elif ext.type == "fw":
                    fw_ext_class = [
                        x
                        for x in IFWExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    fw_ext = fw_ext_class()
                    extension_supported = platform_service.extension_supported(fw_ext)
                    if extension_supported:
                        await fw_ext.setup()
                        registered = True
                elif ext.type == "ipc":
                    ipc_ext_class = [
                        x
                        for x in IIPCExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    ipc_ext = ipc_ext_class()
                    extension_supported = platform_service.extension_supported(ipc_ext)
                    if extension_supported:
                        ipc_service.register_ipc_extension(ipc_ext)
                        registered = True
                elif ext.type == "mh":
                    mh_ext_class = [
                        x
                        for x in IMHExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    mh_ext = mh_ext_class()
                    extension_supported = platform_service.extension_supported(mh_ext)
                    if extension_supported:
                        messaging_service.register_mh_extension(mh_ext)
                        registered = True
                elif ext.type == "rag":
                    rag_ext_class = [
                        x
                        for x in IRAGExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    rag_ext = rag_ext_class()
                    extension_supported = platform_service.extension_supported(rag_ext)
                    if extension_supported:
                        messaging_service.register_rag_extension(rag_ext)
                        registered = True
                elif ext.type == "rpp":
                    rpp_ext_class = [
                        x
                        for x in IRPPExtension.__subclasses__()
                        if x.__module__ == ext.path
                    ][0]
                    rpp_ext = rpp_ext_class()
                    extension_supported = platform_service.extension_supported(rpp_ext)
                    if extension_supported:
                        messaging_service.register_rpp_extension(rpp_ext)
                        registered = True
                else:
                    logger.warning(f"Unknown extension type: {ext.type}.")
            except TypeError as te:
                logger.error("Incomplete subclass implementation.")
                logger.error(te.__traceback__)
                sys.exit(1)
        except IndexError as ie:
            logger.error("Extension not subclass of its intended type.")
            logger.error(ie.__traceback__)
            sys.exit(1)

        if not extension_supported:
            logger.warning(f"Extension not supported by active platforms: {ext.path}.")

        if registered:
            logger.debug(f"Registered {ext.type.upper()} extension: {ext.path}.")


async def run_telnet_client(
    logger=di.container.logging_gateway,
    telnet_client: ITelnetClient = di.container.telnet_client,
) -> None:
    """Run assistant for Telnet server."""

    async with telnet_client as client:
        try:
            await asyncio.create_task(client.start_server())
            logger.debug("Telnet client started.")
        except asyncio.exceptions.CancelledError:
            logger.error("Telnet client shutting down.")


async def run_matrix_client(
    config: SimpleNamespace = di.container.config,
    logger=di.container.logging_gateway,
    matrix_client: IMatrixClient = di.container.matrix_client,
) -> None:
    """Run assistant for the Matrix platform."""

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
        except asyncio.exceptions.CancelledError:
            logger.error("Matrix client shutting down.")


async def run_whatsapp_client(
    logger=di.container.logging_gateway,
    whatsapp_client: IWhatsAppClient = di.container.whatsapp_client,
) -> None:
    """Run assistant for the whatsapp platform."""
    await asyncio.gather(asyncio.create_task(whatsapp_client.init()))
    logger.debug("WhatsApp client started.")
