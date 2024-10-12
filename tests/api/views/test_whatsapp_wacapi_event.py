"""Provides unit tests for the whatsapp_wacapi_event endpoint."""

import asyncio
import hashlib
import hmac
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.views import whatsapp_wacapi_event
from mugen.core.contract.service.ipc import IIPCService


class TestWhatsAppWACAPIEvent(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_wacapi_event endpoint."""

    async def test_json_decode_error(self):
        """Test response when data cannot be decoded."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy app secret.
        app_secret = "test_app_secret"

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "BASEDIR": "",
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
                whatsapp=SimpleNamespace(
                    servers=SimpleNamespace(
                        allowed=lambda: "",
                        verify_ip=lambda: True,
                    ),
                    app=SimpleNamespace(
                        secret=lambda: app_secret,
                    ),
                ),
            ),
        }

        # Create dummy request data and hex signature.
        request_data = ""
        digest = hmac.new(
            key=app_secret.encode(),
            msg=request_data.encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
            "X-Hub-Signature-256": f"sha256={digest}",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            data="",
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
                target="builtins.open", new=dummy_file
            ), self.assertRaises(werkzeug.exceptions.InternalServerError):
                await whatsapp_wacapi_event()

    async def test_ipc_service_unavailable(self):
        """Test response when IPC service unavailable."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy app secret.
        app_secret = "test_app_secret"

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "BASEDIR": "",
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
                whatsapp=SimpleNamespace(
                    servers=SimpleNamespace(
                        allowed=lambda: "",
                        verify_ip=lambda: True,
                    ),
                    app=SimpleNamespace(
                        secret=lambda: app_secret,
                    ),
                ),
            ),
        }

        # Create dummy request data and hex signature.
        request_data = '{"test": "data"}'
        digest = hmac.new(
            key=app_secret.encode(),
            msg=request_data.encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
            "X-Hub-Signature-256": f"sha256={digest}",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            data=request_data,
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Internal Server Error.
            with unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
                target="builtins.open", new=dummy_file
            ), self.assertRaises(werkzeug.exceptions.InternalServerError):
                await whatsapp_wacapi_event()

    async def test_ipc_service_available(self):
        """Test response when IPC service is available."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy app secret.
        app_secret = "test_app_secret"

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "BASEDIR": "",
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["whatsapp"],
                ),
                whatsapp=SimpleNamespace(
                    servers=SimpleNamespace(
                        allowed=lambda: "",
                        verify_ip=lambda: True,
                    ),
                    app=SimpleNamespace(
                        secret=lambda: app_secret,
                    ),
                ),
            ),
        }

        # Create dummy request data and hex signature.
        request_data = '{"test": "data"}'
        digest = hmac.new(
            key=app_secret.encode(),
            msg=request_data.encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
            "X-Hub-Signature-256": f"sha256={digest}",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

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
            "/whatsapp/wacapi/webhook",
            headers=headers,
            data=request_data,
        ):
            # Patch logger to suppress output, and
            # Patch asyncio.Queue to return dummy queue.
            with unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
                target="builtins.open", new=dummy_file
            ), unittest.mock.patch("quart.current_app.logger"), unittest.mock.patch(
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
                response = await whatsapp_wacapi_event()
                self.assertEqual(response["response"], "Ok")
