"""Provides unit tests for the whatsapp_index endpoint."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.views import whatsapp_index
from mugen.core.contract.service.ipc import IIPCService


class TestWhatsAppIndex(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_index endpoint."""

    async def test_ipc_service_unavailable(self):
        """Test whatsapp_index response when di not initialized."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
        }

        # Use dummy app context.
        async with app.app_context():
            with unittest.mock.patch("quart.current_app.logger"), self.assertRaises(
                werkzeug.exceptions.InternalServerError
            ):
                await whatsapp_index()

    async def test_ipc_service_available(self):
        """Test whatsapp_index response when di not initialized."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
            ),
        }

        app.di = SimpleNamespace(
            ipc_service=lambda: unittest.mock.Mock(IIPCService),
        )

        queue = asyncio.Queue()
        get_queue = unittest.mock.Mock()
        get_queue.return_value = queue

        # Use dummy app context.
        async with app.app_context():
            with unittest.mock.patch(target="asyncio.Queue", new=get_queue):
                # This function allows the while loop that checks
                # the response queue to execute until data is placed
                # in the queue.
                async def delayed_put() -> None:
                    """Delay adding info to response queue."""
                    await asyncio.sleep(0.1)
                    await queue.put({"response": "Ok"})

                asyncio.create_task(delayed_put())
                response = await whatsapp_index()
                self.assertEqual(response["status"], "Ok")
