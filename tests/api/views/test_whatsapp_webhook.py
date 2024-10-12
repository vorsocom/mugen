"""Provides unit tests for the whatsapp_webhook endpoint."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.views import whatsapp_webhook
from mugen.core.contract.service.ipc import IIPCService


class TestWhatsAppIPC(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_webhook endpoint."""

    async def test_json_data_none(self):
        """Test whatsapp_webhook response when JSON data not provided."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
            "DEBUG": True,
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/webhook", json=None
        ):
            # Patch logger to suppress output, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.InternalServerError
            ):
                await whatsapp_webhook()

    async def test_json_data_no_command(self):
        """Test whatsapp_webhook response when no command supplied in JSON data."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
            "DEBUG": True,
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/webhook", json={"test": "testing"}
        ):
            # Patch logger to suppress output, and
            # Expect Bad Request Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.BadRequest
            ):
                await whatsapp_webhook()

    async def test_json_data_empty_command(self):
        """Test whatsapp_webhook response when empty command supplied."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
            "DEBUG": True,
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/webhook", json={"command": ""}
        ):
            # Patch logger to suppress output, and
            # Expect Bad Request Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.BadRequest
            ):
                await whatsapp_webhook()

    async def test_ipc_service_unavailable(self):
        """Test whatsapp_webhook response when IPC service unavailable."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
            "DEBUG": True,
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/webhook", json={"command": "test_command"}
        ):
            # Patch logger to suppress output, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.InternalServerError
            ):
                await whatsapp_webhook()

    async def test_ipc_service_available(self):
        """Test whatsapp_webhook response when IPC service is available."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
            "DEBUG": True,
        }

        # Create dummy di object with IPC service.
        app.di = SimpleNamespace(
            ipc_service=lambda: unittest.mock.Mock(IIPCService),
        )

        # Create dummy queue to use as response queue.
        queue = asyncio.Queue()
        get_queue = unittest.mock.Mock()
        get_queue.return_value = queue

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/webhook", json={"command": "test_command"}
        ):
            # Patch logger to suppress output, and
            # Patch asyncio.Queue to return dummy queue.
            with unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
                target="asyncio.Queue", new=get_queue
            ):
                await queue.put({"response": "Ok"})
                response = await whatsapp_webhook()
                self.assertEqual(response["response"], "Ok")
