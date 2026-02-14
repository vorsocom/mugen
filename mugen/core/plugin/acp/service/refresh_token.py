"""Provides a service for the RefreshToken declarative model."""

__all__ = ["RefreshTokenService"]

import uuid
from types import SimpleNamespace

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IRefreshTokenService
from mugen.core.plugin.acp.domain import RefreshTokenDE


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


class RefreshTokenService(
    IRelationalService[RefreshTokenDE],
    IRefreshTokenService,
):
    """A service for the RefreshToken declarative model."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        logger_provider=_logger_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=RefreshTokenDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

        self._config: SimpleNamespace = config_provider()
        self._logger: ILoggingGateway = logger_provider()

        self._ph = PasswordHasher(
            time_cost=self._config.acp.argon2.time_cost,
            memory_cost=self._config.acp.argon2.memory_cost,
            parallelism=self._config.acp.argon2.parallelism,
            hash_len=self._config.acp.argon2.hash_len,
        )

    def generate_refresh_token_hash(self, token: str) -> str:
        return self._ph.hash(token + self._config.acp.refresh_token_pepper)

    async def verify_refresh_token_hash(
        self,
        token_hash: str,
        token: str,
        jti: uuid.UUID,
    ) -> bool:
        try:
            self._ph.verify(
                token_hash,
                token + self._config.acp.refresh_token_pepper,
            )
            if self._ph.check_needs_rehash(token_hash):
                try:
                    await self.update(
                        {"token_jti": jti},
                        {"token_hash": self.generate_refresh_token_hash(token)},
                    )
                except SQLAlchemyError:
                    self._logger.debug("Could not rehash token")
            return True
        except VerificationError:
            self._logger.error("Token hash verification error.")
            return False
