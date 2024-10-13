"""Quart application package."""

__all__ = ["create_quart_app", "run_assistants"]

import asyncio
from importlib import import_module
import os
import sys

from quart import Quart, g
import tomlkit

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.di import DIContainer

from mugen.config import AppConfig

from .core.api import api

mugen = Quart(__name__)

di = DIContainer()


def create_quart_app(basedir: str):
    """Application factory."""
    try:
        with open(f"{basedir}{os.sep}mugen.toml", "r", encoding="utf8") as f:
            config = tomlkit.loads(f.read()).value
            di.config.from_dict(config)
    except FileNotFoundError:
        mugen.logger.error("Configuration file not found.")
        sys.exit(1)

    # Check for valid configuration name.
    environment = di.config.mugen.environment()
    if environment not in ("default", "development", "testing", "production"):
        mugen.logger.error("Invalid configuration name.")
        sys.exit(1)

    # Create application configuration object.
    mugen.config.from_object(AppConfig[environment])
    mugen.config["ENV"] = di.config

    # Get log level and base directory from environment.
    di.config.mugen.logger.level.from_value(mugen.config["LOG_LEVEL"])
    di.config.basedir.from_value(mugen.config["BASEDIR"])

    # Get logger.
    logging_gateway = di.logging_gateway()
    logging_gateway.warning(f"Creating app with {environment} configuration.")

    # Initialize application.
    AppConfig[environment].init_app(mugen)

    # Ensure that API endpoints can access the ipc_queue
    # through current_app.ipc_queue
    mugen.di = di

    # Return the built application object.
    return mugen


# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
# pylint: disable=too-many-branches
async def run_assistants() -> None:
    """Entrypoint for assistants."""
    # Dependency Injection.
    basedir = di.config.basedir()
    di.config.dbm_keyval_storage_path.from_value(
        os.path.join(basedir, "data", "storage.db")
    )
    di.config.matrix.olm_store_path.from_value(
        os.path.join(basedir, "data", ".olmstore")
    )

    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    # Load extensions if specified. These include:
    # 1. Conversational Trigger (CT) extensions.
    # 2. Context (CTX) extensions.
    # 3. Inter-Process Communication (IPC) extensions.
    # 4. Message Handler (MH) extensions.
    # 5. Retrieval Augmented Generation (RAG) extensions.
    # 6. Response Pre-Processor (RPP) extensions.
    extensions = []

    # Load core plugins.
    if di.config.mugen.modules.core.plugins() is not None:
        extensions += di.config.mugen.modules.core.plugins()

    # Load third party extensions.
    if di.config.mugen.modules.extensions() is not None:
        extensions += di.config.mugen.modules.extensions()

    # Wire the extensions for dependency injection.
    di.wire([x["path"] for x in extensions])

    # CT, IPC, and RAG extensions need to be registered
    # with the IPC and Messaging services.
    ipc_service = di.ipc_service()
    messaging_service = di.messaging_service()
    platform_service = di.platform_service()

    # Register the extensions.
    try:
        for ext in extensions:
            ext_type = ext["type"]
            ext_path = ext["path"]
            registered = False

            import_module(name=ext_path)

            if ext_type == "ct":
                ct_ext_class = [
                    x for x in ICTExtension.__subclasses__() if x.__module__ == ext_path
                ][0]
                ct_ext = ct_ext_class()
                if platform_service.extension_supported(ct_ext):
                    messaging_service.register_ct_extension(ct_ext)
                    registered = True
            elif ext_type == "ctx":
                ctx_ext_class = [
                    x
                    for x in ICTXExtension.__subclasses__()
                    if x.__module__ == ext_path
                ][0]
                ctx_ext = ctx_ext_class()
                if platform_service.extension_supported(ctx_ext):
                    messaging_service.register_ctx_extension(ctx_ext)
                    registered = True
            elif ext_type == "fw":
                fw_ext_class = [
                    x for x in IFWExtension.__subclasses__() if x.__module__ == ext_path
                ][0]
                fw_ext = fw_ext_class()
                if platform_service.extension_supported(fw_ext):
                    await fw_ext.setup()
                    registered = True
            elif ext_type == "ipc":
                ipc_ext_class = [
                    x
                    for x in IIPCExtension.__subclasses__()
                    if x.__module__ == ext_path
                ][0]
                ipc_ext = ipc_ext_class()
                if platform_service.extension_supported(ipc_ext):
                    ipc_service.register_ipc_extension(ipc_ext)
                    registered = True
            elif ext_type == "mh":
                mh_ext_class = [
                    x for x in IMHExtension.__subclasses__() if x.__module__ == ext_path
                ][0]
                mh_ext = mh_ext_class()
                if platform_service.extension_supported(mh_ext):
                    messaging_service.register_mh_extension(mh_ext)
                    registered = True
            elif ext_type == "rag":
                rag_ext_class = [
                    x
                    for x in IRAGExtension.__subclasses__()
                    if x.__module__ == ext_path
                ][0]
                rag_ext = rag_ext_class()
                if platform_service.extension_supported(rag_ext):
                    messaging_service.register_rag_extension(rag_ext)
                    registered = True
            elif ext_type == "rpp":
                rpp_ext_class = [
                    x
                    for x in IRPPExtension.__subclasses__()
                    if x.__module__ == ext_path
                ][0]
                rpp_ext = rpp_ext_class()
                if platform_service.extension_supported(rpp_ext):
                    messaging_service.register_rpp_extension(rpp_ext)
                    registered = True
            if registered:
                logging_gateway.debug(
                    f"Registered {ext_type.upper()} extension: {ext_path}"
                )
    except (IndexError, TypeError) as e:
        logging_gateway.error(e.__traceback__)
        sys.exit(1)

    # Register blueprints after extensions have been loaded.
    # This allows extensions to hack the api.
    mugen.register_blueprint(api, url_prefix="/api")

    tasks = []
    platforms = di.config.mugen.platforms()

    try:
        # Run Telnet assistant.
        if "telnet" in platforms:
            tasks.append(asyncio.create_task(run_telnet_client()))

        # Run Matrix assistant.
        if "matrix" in platforms:
            tasks.append(asyncio.create_task(run_matrix_assistant()))

        # Run Whatsapp assistant.
        if "whatsapp" in platforms:
            tasks.append(asyncio.create_task(run_whatsapp_assistant()))

        await asyncio.gather(*tasks)
    except asyncio.exceptions.CancelledError:
        if di.whatsapp_client() is not None:
            await di.whatsapp_client().close()


async def run_telnet_client() -> None:
    """Run assistant for Telnet server."""
    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    telnet_client: ITelnetClient
    async with di.telnet_client() as telnet_client:
        try:
            await asyncio.create_task(telnet_client.start_server())
        except asyncio.exceptions.CancelledError:
            logging_gateway.debug("Telnet client shutting down.")


async def run_matrix_assistant() -> None:
    """Run assistant for the Matrix platform."""
    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    # Initialise matrix client.
    matrix_client: IMatrixClient
    async with di.matrix_client() as matrix_client:
        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_first_sync():
            # Wait for first sync to complete.
            await matrix_client.synced.wait()

            # Set profile name if it's not already set.
            profile = await matrix_client.get_profile()
            assistant_display_name = di.config.matrix_assistant_display_name()
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


async def run_whatsapp_assistant() -> None:
    """Run assistant for the whatsapp platform."""
    await asyncio.gather(asyncio.create_task(di.whatsapp_client().init()))
