"""Provides unit tests for mugen.run_matrix_client."""

import asyncio
from types import SimpleNamespace, TracebackType
from typing import Type
import unittest
import unittest.mock

from quart import Quart

from mugen import run_matrix_client


class TestMuGenInitRunMatrixClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_matrix_client."""

    async def test_normal_run(self) -> None:
        """Test normal run of matrix client."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClientNormal:
            """Dummy matrix client."""

            synced = unittest.mock.AsyncMock()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock()
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.MagicMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_matrix_client(
                config=config,
                logger=app.logger,
                matrix_client=DummyMatrixClientNormal(),
            )
            self.assertEqual(logger.output[0], "DEBUG:test_app:Matrix client started.")

    async def test_normal_run_matching_displayname(self) -> None:
        """Test normal run of matrix client when current and proposed display
        names match.
        """
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClientNormal:
            """Dummy matrix client."""

            synced = unittest.mock.AsyncMock()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock()
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.MagicMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_matrix_client(
                config=config,
                logger=app.logger,
                matrix_client=DummyMatrixClientNormal(),
            )
            self.assertEqual(logger.output[0], "DEBUG:test_app:Matrix client started.")

    async def test_cancelled_error(self) -> None:
        """Test effects of asyncio.exceptions.CancelledError."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            """Dummy matrix client."""

            synced = unittest.mock.AsyncMock()
            profile = unittest.mock.Mock()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=asyncio.exceptions.CancelledError
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.MagicMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_matrix_client(
                config=config,
                logger=app.logger,
                matrix_client=DummyMatrixClient(),
            )
            self.assertEqual(
                logger.output[0], "ERROR:test_app:Matrix client shutting down."
            )
