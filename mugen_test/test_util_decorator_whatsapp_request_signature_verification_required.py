"""Provides unit tests for whatsapp_request_signature_verification_required."""

import hashlib
import hmac
import secrets
from types import SimpleNamespace
import unittest

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen_util.decorator import whatsapp_request_signature_verification_required


class TestWhatsAppRequestSigVerificationRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for whatsapp_request_signature_verification_required."""

    async def test_config_variable_not_set(self):
        """Test output when whatsapp.app.secret is not set."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace()

        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_request_signature_verification_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                await endpoint()

    async def test_x_hub_signature_header_not_set(self):
        """Test output when X-Hub-Signature header is not set."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                app=SimpleNamespace(
                    secret="",
                ),
            ),
        )

        # Use dummy app context.
        async with app.app_context(), app.test_request_context("test"):

            # Define and patch dummy endpoint.
            @whatsapp_request_signature_verification_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.BadRequest),
            ):
                await endpoint()

    async def test_x_hub_signature_header_is_set_incorrect_hash(self):
        """Test output when X-Hub-Signature header is set with incorrect hash."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Generate token to use as app secret.
        app_secret = secrets.token_urlsafe()

        # Create dummy config for testing.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                app=SimpleNamespace(
                    secret=app_secret,
                ),
            ),
        )

        # Set data and calculate hex digest to create dummy request.
        request_data = "test data"

        # Create header object for request context.
        headers = {
            "X-Hub-Signature-256": "incorrecthashlksdk030920",
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "test",
            data=request_data,
            headers=headers,
        ):
            # Define and patch dummy endpoint.
            @whatsapp_request_signature_verification_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.Unauthorized),
            ):
                await endpoint()

    async def test_x_hub_signature_header_is_set_correct_hash(self):
        """Test output when X-Hub-Signature header is set with correct hash."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Generate token to use as app secret.
        app_secret = secrets.token_urlsafe()

        # Create dummy config for testing.
        config = SimpleNamespace(
            whatsapp=SimpleNamespace(
                app=SimpleNamespace(
                    secret=app_secret,
                ),
            ),
        )

        # Set data and calculate hex digest to create dummy request.
        request_data = "test data"
        digest = hmac.new(
            key=app_secret.encode(),
            msg=request_data.encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Create header object for request context.
        headers = {
            "X-Hub-Signature-256": f"sha256={digest}",
        }

        # Use dummy app context.
        async with app.app_context(), app.test_request_context(
            "test",
            data=request_data,
            headers=headers,
        ):
            # Define and patch dummy endpoint.
            @whatsapp_request_signature_verification_required(config=config)
            async def endpoint(*_args, **_kwargs):
                pass

            with self.assertNoLogs():
                await endpoint()
