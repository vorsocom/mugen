"""Quart application package."""

__all__ = ["create_quart_app", "run_assistants"]

import asyncio
from importlib import import_module
import os
import sys

from quart import Quart, g
import tomlkit

from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
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
    with open(f"{basedir}{os.sep}mugen.toml", "r", encoding="utf8") as f:
        config = tomlkit.loads(f.read()).value
        di.config.from_dict(config)

    #
    os.environ["MUGEN_BASEDIR"] = basedir

    # di.config.from_dict(dict((k.lower(), v) for k, v in dotenv_values().items()))
    env_config = di.config

    # Check for valid configuration name.
    config_name = env_config.mugen.config()
    if config_name not in ("default", "development", "testing", "production"):
        print("Invalid configuration name.")
        sys.exit(1)

    mugen.logger.warning("Creating app with %s configuration.", config_name)

    # Create application configuration object.
    mugen.config.from_object(AppConfig[config_name])
    mugen.config["ENV"] = di.config

    # Get log level and base directory from environment.
    di.config.mugen.logger.level.from_value(mugen.config["LOG_LEVEL"])
    di.config.basedir.from_value(mugen.config["BASEDIR"])

    # Initialize application.
    AppConfig[config_name].init_app(mugen)

    # Register blueprints.
    mugen.register_blueprint(api, url_prefix="/api")

    @mugen.after_request
    def call_after_request_callbacks(response):
        """Ensure all registered after-request-callbacks are called."""
        for callback in getattr(g, "after_request_callbacks", ()):
            callback(response)
        return response

    # Ensure that API endpoints can access the ipc_queue
    # through current_app.ipc_queue
    mugen.matrix_ipc_queue = di.matrix_ipc_queue()
    mugen.whatsapp_ipc_queue = di.whatsapp_ipc_queue()

    # Return the built application object.
    return mugen


# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
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

    # Load core plugins.
    extensions = di.config.mugen.modules.core.plugins()

    # Load third party extensions.
    extensions += di.config.mugen.modules.extensions()

    # Wire the extensions for dependency injection.
    di.wire(extensions)

    # CT, IPC, and RAG extensions need to be registered
    # with the IPC and Messaging services.
    ipc_service = di.ipc_service()
    messaging_service = di.messaging_service()

    def platforms_supported(ext) -> bool:
        """Filter extensions that are not needed."""
        if ext.platforms == []:
            return True

        return len(list(set(ext.platforms) & set(di.config.mugen.platforms()))) != 0

    # Register the extensions.
    try:
        for ext in extensions:
            import_module(name=ext)

            if "ct_ext_" in ext:
                ct_ext_class = [
                    x for x in ICTExtension.__subclasses__() if x.__module__ == ext
                ][0]
                ct_ext = ct_ext_class()
                if platforms_supported(ct_ext):
                    messaging_service.register_ct_extension(ct_ext)
                    logging_gateway.debug(f"Registered CT extension: {ext}")

            if "ctx_ext_" in ext:
                ctx_ext_class = [
                    x for x in ICTXExtension.__subclasses__() if x.__module__ == ext
                ][0]
                ctx_ext = ctx_ext_class()
                if platforms_supported(ctx_ext):
                    messaging_service.register_ctx_extension(ctx_ext)
                    logging_gateway.debug(f"Registered CTX extension: {ext}")

            if "ipc_ext_" in ext:
                ipc_ext_class = [
                    x for x in IIPCExtension.__subclasses__() if x.__module__ == ext
                ][0]
                ipc_ext = ipc_ext_class()
                if platforms_supported(ipc_ext):
                    ipc_service.register_ipc_extension(ipc_ext)
                    logging_gateway.debug(f"Registered IPC extension: {ext}")

            if "mh_ext_" in ext:
                mh_ext_class = [
                    x for x in IMHExtension.__subclasses__() if x.__module__ == ext
                ][0]
                mh_ext = mh_ext_class()
                if platforms_supported(mh_ext):
                    messaging_service.register_mh_extension(mh_ext)
                    logging_gateway.debug(f"Registered MH extension: {ext}")

            if "rag_ext_" in ext:
                rag_ext_class = [
                    x for x in IRAGExtension.__subclasses__() if x.__module__ == ext
                ][0]
                rag_ext = rag_ext_class()
                if platforms_supported(rag_ext):
                    messaging_service.register_rag_extension(rag_ext)
                    logging_gateway.debug(f"Registered RAG extension: {ext}")

            if "rpp_ext_" in ext:
                rpp_ext_class = [
                    x for x in IRPPExtension.__subclasses__() if x.__module__ == ext
                ][0]
                rpp_ext = rpp_ext_class()
                if platforms_supported(rpp_ext):
                    messaging_service.register_rpp_extension(rpp_ext)
                    logging_gateway.debug(f"Registered RPP extension: {ext}")
    except TypeError as e:
        logging_gateway.error(e.__traceback__)
        sys.exit(1)

    tasks = []
    platforms = di.config.mugen.platforms()

    # Run Matrix assistant.
    if "matrix" in platforms:
        tasks.append(asyncio.create_task(run_matrix_assistant()))

    # Run Whatsapp assistant.
    if "whatsapp" in platforms:
        tasks.append(asyncio.create_task(run_whatsapp_assistant()))

    await asyncio.gather(*tasks)


async def run_matrix_assistant() -> None:
    """Run assistant for the Matrix platform."""
    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    # Initialise matrix-nio async client.
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
    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    # Initialise WhatsApp client.
    async with di.whatsapp_client() as whatsapp_client:
        try:
            await asyncio.gather(
                asyncio.create_task(
                    whatsapp_client.listen_forever(),
                ),
            )
        except asyncio.exceptions.CancelledError:
            logging_gateway.debug("WhatsApp client shutting down.")
