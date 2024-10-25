"""Provides unit tests for the whatsapp_wacapi_event endpoint."""

import asyncio
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.endpoint import whatsapp_wacapi_event


class TestWhatsAppWACAPIEvent(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_wacapi_event endpoint."""

    async def test_json_decode_error(self):
        """Test response when data cannot be decoded."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Use dummy app context.
        async with (
            app.app_context(),
            app.test_request_context(
                "/whatsapp/wacapi/webhook",
                data="",
            ),
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Internal Server Error.
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await whatsapp_wacapi_event()

    async def test_ipc_service_invalid(self):
        """Test response when IPC service invalid."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy request data.
        request_data = '{"test": "data"}'
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with (
            app.app_context(),
            app.test_request_context(
                "/whatsapp/wacapi/webhook",
                data=request_data,
            ),
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Internal Server Error.
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await whatsapp_wacapi_event(ipc_service=None)

    async def test_normal_execution(self):
        """Test response when endpoint executes normally."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy request data.
        request_data = '{"test": "data"}'

        # Create dummy queue
        # to use as response queue.
        queue = asyncio.Queue()
        get_queue = unittest.mock.Mock()
        get_queue.return_value = queue

        # Use dummy app context.
        async with (
            app.app_context(),
            app.test_request_context(
                "/whatsapp/wacapi/webhook",
                data=request_data,
            ),
        ):
            # Patch logger to suppress output, and
            # Patch asyncio.Queue to return dummy queue.
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
                response = await whatsapp_wacapi_event()
                self.assertEqual(response["response"], "Ok")
