"""Provides unit tests for the matrix_index endpoint."""

import asyncio
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.endpoint import matrix_index


class TestMatrixIndex(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the matrix_index endpoint."""

    async def test_ipc_service_unavailable(self):
        """Test effects of invalid IPC service."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Use dummy app context.
        async with app.app_context():
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await matrix_index(ipc_service=None)

    async def test_normal_execution(self):
        """Test ouput of normal execution."""
        # Create dummy app to get context.
        app = Quart("test")

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
            ):
                # This function allows the while loop that checks
                # the response queue to execute until data is placed
                # in the queue.
                async def delayed_put() -> None:
                    """Delay adding info to response queue."""
                    await asyncio.sleep(0.1)
                    await queue.put({"response": "Ok"})

                asyncio.create_task(delayed_put())
                response = await matrix_index()
                self.assertEqual(response["status"], "Ok")
