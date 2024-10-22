"""Provides unit tests for whatsapp_server_ip_allow_list_required decorator."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.decorators import whatsapp_server_ip_allow_list_required


class TestWhatsAppServerIPAllowListRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for whatsapp_server_ip_allow_list_required decorator."""

    async def test_config_variable_not_set(self):
        """Test decorator output when whatsapp.servers.allowed is not set."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace()

        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_server_ip_allow_list_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await endpoint()

    async def test_allow_list_file_not_found(self):
        """Test decorator output when whatsapp.servers.allowed file is not found."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                servers=SimpleNamespace(
                    allowed="data/test_file.txt",
                ),
            ),
        )

        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_server_ip_allow_list_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await endpoint()

    async def test_verification_required_flag_not_set(self):
        """Test decorator output when verification is not required."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            basedir="",
            whatsapp=SimpleNamespace(
                servers=SimpleNamespace(
                    allowed="",
                ),
            ),
        )

        async with app.app_context():

            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="builtins.open")
            @whatsapp_server_ip_allow_list_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with self.assertLogs(logger="test_app", level="ERROR"):
                await endpoint()

    async def test_verification_required_flag_is_set_invalid_ip(self):
        """Test decorator output when verification is required and ip is invalid."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                servers=SimpleNamespace(
                    allowed="",
                    verify_ip=True,
                ),
            ),
        )

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="192.168.0.0/24")

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "test",
            headers=headers,
        ):
            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="builtins.open", new=dummy_file)
            @whatsapp_server_ip_allow_list_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await endpoint()

    async def test_verification_required_flag_is_set_valid_ip(self):
        """Test decorator output when verification is required and ip is valid."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            basedir="",
            whatsapp=SimpleNamespace(
                servers=SimpleNamespace(
                    allowed="",
                    verify_ip=True,
                ),
            ),
        )

        # Dummy file
        dummy_file = unittest.mock.mock_open(read_data="127.0.0.0/8")

        # Create header object for request context.
        headers = {
            "Remote-Addr": "127.0.0.1",
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "test",
            headers=headers,
        ):
            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="builtins.open", new=dummy_file)
            @whatsapp_server_ip_allow_list_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with self.assertNoLogs():
                await endpoint()
