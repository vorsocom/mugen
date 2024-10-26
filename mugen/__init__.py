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


# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
# pylint: disable=too-many-branches
async def run_clients(app: Quart) -> None:
    """Entrypoint for assistants."""

    # Get logging gateway.
    logging_gateway = di.container.logging_gateway

    # Do platform checks.
    tasks = []
    platforms = di.container.config.mugen.platforms

    try:
        # Run Matrix assistant.
        if "matrix" in platforms:
            tasks.append(asyncio.create_task(run_matrix_client()))

        # Run Telnet assistant.
        if "telnet" in platforms:
            tasks.append(asyncio.create_task(run_telnet_client()))

        # Run Whatsapp assistant.
        if "whatsapp" in platforms:
            tasks.append(asyncio.create_task(run_whatsapp_client()))
    except TypeError:
        logging_gateway.error("Platforms not configured.")
        sys.exit(1)

    # Load extensions if specified. These include:
    # 1. Conversational Trigger (CT) extensions.
    # 2. Context (CTX) extensions.
    # 3. Inter-Process Communication (IPC) extensions.
    # 4. Message Handler (MH) extensions.
    # 5. Retrieval Augmented Generation (RAG) extensions.
    # 6. Response Pre-Processor (RPP) extensions.
    extensions = []

    # Load core plugins.
    if di.container.config.mugen.modules.core.plugins is not None:
        extensions += di.container.config.mugen.modules.core.plugins

    # Load third party extensions.
    if di.container.config.mugen.modules.extensions is not None:
        extensions += di.container.config.mugen.modules.extensions

    # Wire the plugins/extensions for dependency injection.
    # di.container.wire([x["path"] for x in extensions])

    # CT, IPC, and RAG extensions need to be registered
    # with the IPC and Messaging services.
    ipc_service = di.container.ipc_service
    messaging_service = di.container.messaging_service

    # Platform service is needed to check extension support.
    platform_service = di.container.platform_service

    # Register the extensions.
    try:
        for ext in extensions:
            registered = False

            import_module(name=ext.path)

            if ext.type == "ct":
                ct_ext_class = [
                    x for x in ICTExtension.__subclasses__() if x.__module__ == ext.path
                ][0]
                ct_ext = ct_ext_class()
                if platform_service.extension_supported(ct_ext):
                    messaging_service.register_ct_extension(ct_ext)
                    registered = True
            elif ext.type == "ctx":
                ctx_ext_class = [
                    x
                    for x in ICTXExtension.__subclasses__()
                    if x.__module__ == ext.path
                ][0]
                ctx_ext = ctx_ext_class()
                if platform_service.extension_supported(ctx_ext):
                    messaging_service.register_ctx_extension(ctx_ext)
                    registered = True
            elif ext.type == "fw":
                fw_ext_class = [
                    x for x in IFWExtension.__subclasses__() if x.__module__ == ext.path
                ][0]
                fw_ext = fw_ext_class()
                if platform_service.extension_supported(fw_ext):
                    await fw_ext.setup()
                    registered = True
            elif ext.type == "ipc":
                ipc_ext_class = [
                    x
                    for x in IIPCExtension.__subclasses__()
                    if x.__module__ == ext.path
                ][0]
                ipc_ext = ipc_ext_class()
                if platform_service.extension_supported(ipc_ext):
                    ipc_service.register_ipc_extension(ipc_ext)
                    registered = True
            elif ext.type == "mh":
                mh_ext_class = [
                    x for x in IMHExtension.__subclasses__() if x.__module__ == ext.path
                ][0]
                mh_ext = mh_ext_class()
                if platform_service.extension_supported(mh_ext):
                    messaging_service.register_mh_extension(mh_ext)
                    registered = True
            elif ext.type == "rag":
                rag_ext_class = [
                    x
                    for x in IRAGExtension.__subclasses__()
                    if x.__module__ == ext.path
                ][0]
                rag_ext = rag_ext_class()
                if platform_service.extension_supported(rag_ext):
                    messaging_service.register_rag_extension(rag_ext)
                    registered = True
            elif ext.type == "rpp":
                rpp_ext_class = [
                    x
                    for x in IRPPExtension.__subclasses__()
                    if x.__module__ == ext.path
                ][0]
                rpp_ext = rpp_ext_class()
                if platform_service.extension_supported(rpp_ext):
                    messaging_service.register_rpp_extension(rpp_ext)
                    registered = True
            if registered:
                logging_gateway.debug(
                    f"Registered {ext.type.upper()} extension: {ext.path}"
                )
    except (IndexError, TypeError) as e:
        logging_gateway.error(e.__traceback__)
        sys.exit(1)

    # Register blueprints after extensions have been loaded.
    # This allows extensions to hack the api.
    app.register_blueprint(api, url_prefix="/api")

    try:
        await asyncio.gather(*tasks)
    except asyncio.exceptions.CancelledError:
        if di.container.whatsapp_client is not None:
            await di.container.whatsapp_client.close()


async def run_telnet_client() -> None:
    """Run assistant for Telnet server."""

    # Get logging gateway.
    logging_gateway = di.container.logging_gateway

    telnet_client: ITelnetClient
    async with di.container.telnet_client as telnet_client:
        try:
            await asyncio.create_task(telnet_client.start_server())
        except asyncio.exceptions.CancelledError:
            logging_gateway.debug("Telnet client shutting down.")


async def run_matrix_client() -> None:
    """Run assistant for the Matrix platform."""

    # Get logging gateway.
    logging_gateway = di.container.logging_gateway

    # Initialise matrix client.
    matrix_client: IMatrixClient
    async with di.container.matrix_client as matrix_client:
        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_first_sync():
            # Wait for first sync to complete.
            await matrix_client.synced.wait()

            # Set profile name if it's not already set.
            profile = await matrix_client.get_profile()
            assistant_display_name = di.container.config.matrix.assistant.name
            if (
                assistant_display_name is not None
                and profile.displayname != assistant_display_name
            ):
                await matrix_client.set_displayname(assistant_display_name)

            # Cleanup device list and trust known devices.
            # matrix_client.cleanup_known_user_devices_list()
            matrix_client.trust_known_user_devices()

        try:
            # Start process loop.
            await asyncio.gather(
                asyncio.create_task(wait_on_first_sync()),
                asyncio.create_task(
                    matrix_client.sync_forever(
                        since=matrix_client.sync_token,
                        timeout=100,
                        full_state=True,
                        set_presence="online",
                    )
                ),
            )
        except asyncio.exceptions.CancelledError:
            logging_gateway.debug("Matrix client shutting down.")


async def run_whatsapp_client() -> None:
    """Run assistant for the whatsapp platform."""
    await asyncio.gather(asyncio.create_task(di.container.whatsapp_client.init()))
