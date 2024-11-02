"""Provides unit tests for the whatsapp_index endpoint."""

import asyncio
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.endpoint import whatsapp_index


class TestWhatsAppIndex(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_index endpoint."""

    async def test_ipc_service_invalid(self):
        """Test response when IPC service invalid."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Use dummy app context.
        async with app.app_context():
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await whatsapp_index(ipc_service=None)

    async def test_normal_executions(self):
        """Test response when endpoint executes normally."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy queue
        # to use as response queue.
        queue = asyncio.Queue()
        get_queue = unittest.mock.Mock()
        get_queue.return_value = queue

        # Use dummy app context.
        async with app.app_context():
            with (
                unittest.mock.patch(target="asyncio.Queue", new=get_queue),
                unittest.mock.patch(
                    target="mugen.core.di.container.ipc_service.handle_ipc_request"
                ),
                self.assertNoLogs(),
            ):
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
