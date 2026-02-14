"""Unit tests for mugen.core.plugin.acp.service.refresh_token.RefreshTokenService."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from argon2.exceptions import VerificationError
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.plugin.acp.service import refresh_token as refresh_token_module
from mugen.core.plugin.acp.service.refresh_token import RefreshTokenService


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        acp=SimpleNamespace(
            argon2=SimpleNamespace(
                time_cost=1,
                memory_cost=1024,
                parallelism=1,
                hash_len=16,
            ),
            refresh_token_pepper="pepper-1",
        )
    )


class TestMugenAcpServiceRefreshToken(unittest.IsolatedAsyncioTestCase):
    """Covers hash generation and verification/rehash behavior."""

    def test_provider_helpers(self) -> None:
        fake_config = SimpleNamespace()
        fake_logger = Mock()
        with patch.object(
            refresh_token_module.di,
            "container",
            new=SimpleNamespace(config=fake_config, logging_gateway=fake_logger),
        ):
            self.assertIs(refresh_token_module._config_provider(), fake_config)  # pylint: disable=protected-access
            self.assertIs(refresh_token_module._logger_provider(), fake_logger)  # pylint: disable=protected-access

    def _new_service(self):
        svc = RefreshTokenService(
            table="refresh_tokens",
            rsg=SimpleNamespace(),
            config_provider=_config,
            logger_provider=lambda: Mock(),
        )
        return svc

    async def test_generate_hash_and_verify_paths(self) -> None:
        svc = self._new_service()
        self.assertIsInstance(svc.generate_refresh_token_hash("abc"), str)

        svc._ph = SimpleNamespace(  # pylint: disable=protected-access
            verify=Mock(return_value=None),
            check_needs_rehash=Mock(return_value=False),
        )
        ok = await svc.verify_refresh_token_hash("hash", "token", uuid.uuid4())
        self.assertTrue(ok)

        svc._ph = SimpleNamespace(  # pylint: disable=protected-access
            verify=Mock(return_value=None),
            check_needs_rehash=Mock(return_value=True),
            hash=Mock(return_value="rehash-1"),
        )
        svc.update = AsyncMock(return_value=SimpleNamespace())
        ok_rehash = await svc.verify_refresh_token_hash("hash", "token", uuid.uuid4())
        self.assertTrue(ok_rehash)
        svc.update.assert_awaited_once()

        svc._ph = SimpleNamespace(  # pylint: disable=protected-access
            verify=Mock(return_value=None),
            check_needs_rehash=Mock(return_value=True),
            hash=Mock(return_value="rehash-2"),
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("db-issue"))
        ok_rehash_fail = await svc.verify_refresh_token_hash("hash", "token", uuid.uuid4())
        self.assertTrue(ok_rehash_fail)
        svc._logger.debug.assert_called_with("Could not rehash token")  # pylint: disable=protected-access

        svc._ph = SimpleNamespace(  # pylint: disable=protected-access
            verify=Mock(side_effect=VerificationError("bad")),
            check_needs_rehash=Mock(return_value=False),
        )
        failed = await svc.verify_refresh_token_hash("hash", "token", uuid.uuid4())
        self.assertFalse(failed)
        svc._logger.error.assert_called_with("Token hash verification error.")  # pylint: disable=protected-access
