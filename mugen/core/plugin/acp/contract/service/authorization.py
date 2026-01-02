"""
Provides a service contract for RBAC-based control-plane authorization.
"""

import uuid
from abc import ABC, abstractmethod


class IAuthorizationService(ABC):  # pylint: disable=too-few-public-methods
    """A service contract for RBAC-based control-plane authorization."""

    @abstractmethod
    async def has_permission(  # pylint: disable=too-many-arguments
        self,
        *,
        user_id: uuid.UUID,
        permission_object: str,  # namespace:name
        permission_type: str,  # namespace:name
        tenant_id: uuid.UUID | None,
        allow_global_admin: bool = True,
    ) -> bool:
        """Determine if User with `user_id` can execute `permission_type` action on
        `permission_object`.
        """
