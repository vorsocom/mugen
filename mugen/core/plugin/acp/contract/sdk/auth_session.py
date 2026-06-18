"""ACP auth session extension contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from mugen.core.plugin.acp.contract.service import IAuthorizationService
from mugen.core.plugin.acp.domain.user import UserDE

__all__ = [
    "AcpAuthSessionRoleContributor",
    "auth_session_role_contributors",
    "register_auth_session_role_contributor",
]

_AUTH_SESSION_ROLE_CONTRIBUTORS: list[AcpAuthSessionRoleContributor] = []


class AcpAuthSessionRoleContributor(Protocol):
    """Contributes stable role or permission claims to ACP auth sessions."""

    async def session_roles_for_user(
        self,
        *,
        user: UserDE,
        auth_svc: IAuthorizationService,
    ) -> Iterable[str]:
        """Return session-visible role or permission claims for `user`."""


def register_auth_session_role_contributor(
    contributor: AcpAuthSessionRoleContributor,
) -> None:
    """Register an ACP auth-session role contributor."""
    _AUTH_SESSION_ROLE_CONTRIBUTORS.append(contributor)


def auth_session_role_contributors() -> tuple[AcpAuthSessionRoleContributor, ...]:
    """Return registered ACP auth-session role contributors."""
    return tuple(_AUTH_SESSION_ROLE_CONTRIBUTORS)
