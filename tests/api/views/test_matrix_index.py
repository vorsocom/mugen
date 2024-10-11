"""Provides unit tests for the matrix_index endpoint."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.views import matrix_index
from mugen.core.contract.service.ipc import IIPCService


class TestMatrixIndex(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the matrix_index endpoint."""

    async def test_ipc_service_unavailable(self):
        """Test matrix_index response when di not initialized."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
            "DEBUG": True,
        }

        # Use dummy app context.
        async with app.app_context():
            with self.assertRaises(werkzeug.exceptions.InternalServerError):
                await matrix_index()

    async def test_ipc_service_available(self):
        """Test matrix_index response when di not initialized."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix"],
                ),
            ),
            "DEBUG": True,
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
                await queue.put({"response": "Ok"})
                response = await matrix_index()
                self.assertEqual(response["status"], "Ok")
