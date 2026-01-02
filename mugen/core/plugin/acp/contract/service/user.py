"""Provides a service contract for User-related services."""

__all__ = ["IUserService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import UserDE


class IUserService(
    ICrudService[UserDE],
    ABC,
):
    """A service contract for User-related services."""

    @abstractmethod
    async def bump_token_version(self, where: Mapping[str, Any]) -> UserDE | None:
        """Increment a User's token version by 1."""

    @abstractmethod
    async def entity_action_delete(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Soft-delete a User."""

    @abstractmethod
    async def entity_action_lock(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Lock a User."""

    @abstractmethod
    async def entity_action_resetpasswordadmin(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reset a User's password. Performed by an admin."""

    @abstractmethod
    async def entity_action_resetpassworduser(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reset a User's password. Peformed by the user."""

    @abstractmethod
    async def entity_action_unlock(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Unlock a User."""

    @abstractmethod
    async def entity_action_updateprofile(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Update a User's profile (Person)."""

    @abstractmethod
    async def entity_action_updateroles(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Update a User's roles."""

    @abstractmethod
    async def entity_set_action_provision(
        self,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Provision a User."""

    @abstractmethod
    async def get_expanded(self, where: Mapping[str, Any]) -> UserDE | None:
        """Retrieve a User record from the DB, including its related records."""

    @abstractmethod
    def get_password_hash(self, pw: str) -> str:
        """Generate a hash based on the supplied string."""

    @abstractmethod
    def verify_password_hash(self, pw_hash: str, pw: str) -> bool:
        """Check supplied string against password hash."""

    @abstractmethod
    def validate_password_policy(self, pw: str) -> bool:
        """Validate the supplied password against the configured password policy."""
