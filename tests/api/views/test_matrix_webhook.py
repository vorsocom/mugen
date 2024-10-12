"""Provides unit tests for the matrix_webhook endpoint."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.views import matrix_webhook
from mugen.core.contract.service.ipc import IIPCService


class TestMatrixWebhook(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the matrix_webhook endpoint."""

    async def test_json_data_none(self):
        """Test matrix_webhook response when JSON data not provided."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/matrix/webhook", json=None
        ):
            # Patch logger to suppress output, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.InternalServerError
            ):
                await matrix_webhook()

    async def test_json_data_no_command(self):
        """Test matrix_webhook response when no command supplied in JSON data."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/matrix/webhook", json={"test": "testing"}
        ):
            # Patch logger to suppress output, and
            # Expect Bad Request Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.BadRequest
            ):
                await matrix_webhook()

    async def test_json_data_empty_command(self):
        """Test matrix_webhook response when empty command supplied."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/matrix/webhook", json={"command": ""}
        ):
            # Patch logger to suppress output, and
            # Expect Bad Request Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.BadRequest
            ):
                await matrix_webhook()

    async def test_ipc_service_unavailable(self):
        """Test matrix_webhook response when IPC service unavailable."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/matrix/webhook", json={"command": "test_command"}
        ):
            # Patch logger to suppress output, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.InternalServerError
            ):
                await matrix_webhook()

    async def test_ipc_service_available(self):
        """Test matrix_webhook response when IPC service is available."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
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
            "/matrix/webhook", json={"command": "test_command"}
        ):
            # Patch logger to suppress output, and
            # Patch asyncio.Queue to return dummy queue.
            with unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
                target="asyncio.Queue", new=get_queue
            ):
                # This function allows the while loop that checks
                # the response queue to execute until data is placed
                # in the queue.
                async def delayed_put() -> None:
                    """Delay adding info to response queue."""
                    await asyncio.sleep(0.1)
                    await queue.put({"response": "Ok"})

                asyncio.create_task(delayed_put())
                response = await matrix_webhook()
                self.assertEqual(response["response"], "Ok")