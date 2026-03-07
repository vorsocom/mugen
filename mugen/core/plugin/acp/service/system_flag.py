"""Provides a service for the SystemFlag declarative model."""

__all__ = ["SystemFlagService"]

import uuid
from typing import Any

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service import ISystemFlagService
from mugen.core.plugin.acp.domain import SystemFlagDE
from mugen.core.service.platform_runtime_reload import (
    PlatformRuntimeProfileReloadError,
    reload_platform_runtime_profiles,
)


class SystemFlagService(
    IRelationalService[SystemFlagDE],
    ISystemFlagService,
):
    """A service for the SystemFlag declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SystemFlagDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def entity_set_action_reloadPlatformProfiles(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reload live multi-profile platform runtimes."""
        _ = auth_user_id
        _ = data
        try:
            result = await reload_platform_runtime_profiles(
                injector=di.container.build(),
            )
        except PlatformRuntimeProfileReloadError as exc:
            abort(exc.status_code, str(exc))

        return dict(result), 200
