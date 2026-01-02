"""Provides a service contract for RefreshToken-related services."""

__all__ = ["IRefreshTokenService"]

import uuid
from abc import ABC, abstractmethod

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import RefreshTokenDE


class IRefreshTokenService(
    ICrudService[RefreshTokenDE],
    ABC,
):
    """A service contract for RefreshToken-related services."""

    @abstractmethod
    def generate_refresh_token_hash(self, token: str) -> str:
        """Generate a hash of the supplied token."""

    @abstractmethod
    async def verify_refresh_token_hash(
        self,
        token_hash: str,
        token: str,
        jti: uuid.UUID,
    ) -> bool:
        """Verify supplied token against hash."""
