"""Provides unit tests for the whatsapp_wacapi_subscription endpoint."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.endpoint import whatsapp_wacapi_subscription


class TestWhatsAppWACAPISubscription(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the whatsapp_wacapi_subscription endpoint."""

    async def test_hub_mode_unavailable_or_incorrect(self):
        """Test response when hub.mode is unavailable or incorrect."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Bad Request.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.BadRequest),
            ):
                await whatsapp_wacapi_subscription(config=None)

    async def test_hub_verify_token_unavailable_or_empty(self):
        """Test response when hub.verify_token is unavailable or empty."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "",
            },
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Bad Request.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.BadRequest),
            ):
                await whatsapp_wacapi_subscription(config=None)

    async def test_config_verification_token_unavailable(self):
        """Test response when config verification token is unavailable."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "test",
            },
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Internal Server Error.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await whatsapp_wacapi_subscription(config=None)

    async def test_hub_verify_token_incorrect(self):
        """Test response when hub.verify_token is incorrect."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Dummy verification token.
        verification_token = "test_verification_token"

        # Create dummy config object to patch current_app.config.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                webhook=SimpleNamespace(
                    verification_token=verification_token,
                ),
            ),
        )

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "incorrect_test_verification_token",
            },
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Bad Request.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.BadRequest),
            ):
                await whatsapp_wacapi_subscription(config=config)

    async def test_hub_challenge_unavailable_or_empty(self):
        """Test response when hub.challenge is not supplied or is empty."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Dummy verification token.
        verification_token = "test_verification_token"

        # Create dummy config.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                webhook=SimpleNamespace(
                    verification_token=verification_token,
                ),
            ),
        )

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": verification_token,
            },
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Bad Request.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.BadRequest),
            ):
                await whatsapp_wacapi_subscription(config=config)

    async def test_hub_challenge_available(self):
        """Test response when hub.challenge is supplied."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Dummy verification token.
        verification_token = "test_verification_token"

        # Create dummy config.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                webhook=SimpleNamespace(
                    verification_token=verification_token,
                ),
            ),
        )

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "/whatsapp/wacapi/webhook",
            headers=headers,
            json={"command": "test_command"},
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": verification_token,
                "hub.challenge": "test_challenge",
            },
        ):
            # Patch logger to suppress output, and
            # Patch builtins.open, and
            # Expect Bad Request.
            with (
                unittest.mock.patch(target="builtins.open", new=dummy_file),
                self.assertNoLogs(),
            ):
                await whatsapp_wacapi_subscription(config=config)
