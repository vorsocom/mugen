"""Quart application package."""

__all__ = ["create_quart_app", "run_matrix_assistant"]

import asyncio
from importlib import import_module
import json
import os
import sys

from dotenv import dotenv_values
from quart import Quart, g

from app.core.contract.ct_extension import ICTExtension
from app.core.contract.ipc_extension import IIPCExtension
from app.core.contract.rag_extension import IRAGExtension
from app.core.di import DIContainer

from config import AppConfig

from .core.api import api_bp

app = Quart(__name__)

di = DIContainer()


def create_quart_app(config_name):
    """Application factory."""
    # Check for valid configuration name.
    if config_name not in ("default", "development", "testing", "production"):
        print("Invalid configuration name.")
        sys.exit(1)

    app.logger.warning("Creating app with %s configuration.", config_name)

    # Create application configuration object.
    app.config.from_object(AppConfig[config_name])

    # Initialize application.
    AppConfig[config_name].init_app(app)

    # Register blueprints.
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.after_request
    def call_after_request_callbacks(response):
        """Ensure all registered after-request-callbacks are called."""
        for callback in getattr(g, "after_request_callbacks", ()):
            callback(response)
        return response

    # Ensure that API endpoints can access the ipc_queue
    # through current_app.ipc_queue
    app.ipc_queue = di.ipc_queue()

    # Return the built application object.
    return app


# pylint: disable=too-many-locals
async def run_matrix_assistant(basedir: str, log_level: int) -> None:
    """Application entrypoint."""
    # Dependency injection.
    di.config.from_dict(dict((k.lower(), v) for k, v in dotenv_values().items()))
    di.config.log_level.from_value(log_level)
    di.config.basedir.from_value(basedir)
    di.config.keyval_storage_path.from_value(f"{basedir}/data/storage.db")
    di.config.matrix_olm_store_path.from_value(
        os.path.join(
            basedir,
            "data",
            ".olmstore",
        )
    )

    with open(f"{basedir}/conf/persona.txt", encoding="utf8") as f:
        di.config.assistant_persona.from_value(f.read())

    # Get logging gateway.
    logging_gateway = di.logging_gateway()

    # Initialise matrix-nio async client.
    async with di.client() as client:
        # Load extensions. These include:
        # 1. Retrieval Augmented Generation (RAG) extensions.
        # 2. Inter-Process Communication (IPC) extensions.
        # 3. Conversational Trigger (CT) extensions.
        extensions = json.loads(di.config.gloria_extension_modules())

        # Wire the extensions for dependency injection.
        di.wire(extensions)

        # CT, IPC, and RAG extensions need to be registered
        # with the IPC and Messaging services.
        ipc_service = di.ipc_service()
        messaging_service = di.messaging_service()

        # Register the extensions.
        for ext in extensions:
            import_module(name=ext)

            if "ct_extension" in ext:
                ct_ext_class = [
                    x for x in ICTExtension.__subclasses__() if x.__module__ == ext
                ][0]
                ct_ext = ct_ext_class()
                messaging_service.register_ct_extension(ct_ext)
                logging_gateway.debug(f"Registered CT extension: {ext}")

            if "ipc_extension" in ext:
                ipc_ext_class = [
                    x for x in IIPCExtension.__subclasses__() if x.__module__ == ext
                ][0]
                ipc_ext = ipc_ext_class()
                ipc_service.register_ipc_extension(ipc_ext)
                logging_gateway.debug(f"Registered IPC extension: {ext}")

            if "rag_extension" in ext:
                rag_ext_class = [
                    x for x in IRAGExtension.__subclasses__() if x.__module__ == ext
                ][0]
                rag_ext = rag_ext_class()
                messaging_service.register_rag_extension(rag_ext)
                logging_gateway.debug(f"Registered RAG extension: {ext}")

        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_first_sync():
            # Wait for first sync to complete.
            await client.synced.wait()

            # Set profile name if it's not already set.
            profile = await client.get_profile()
            agent_display_name = di.config.matrix_agent_display_name()
            if (
                agent_display_name is not None
                and profile.displayname != agent_display_name
            ):
                await client.set_displayname(agent_display_name)

            # Cleanup device list and trust known devices.
            client.cleanup_known_user_devices_list()
            client.trust_known_user_devices()

        # Start process loop.
        asyncio.gather(
            asyncio.create_task(wait_on_first_sync()),
            asyncio.create_task(
                client.sync_forever(
                    1000,
                    since=client.sync_token,
                    full_state=True,
                    set_presence="online",
                )
            ),
        )
