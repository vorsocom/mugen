"""Provides an implementation of IFWExtension for the admin plugin."""

__all__ = ["AdminFWExtension"]

from types import SimpleNamespace

from quart import Quart
from quart_cors import cors

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.migration.loader import contribute_all
from mugen.core.plugin.acp.service.authorization import AuthorizationService
from mugen.core.plugin.acp.service.jwt_eddsa import EdDsaJwtService
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder


class AdminFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """An implementation of IFWFramework for the admin plugin."""

    def __init__(
        self,
        config_provider=lambda: di.container.config,
        rsg_provider=lambda: di.container.relational_storage_gateway,
    ) -> None:
        self._config: SimpleNamespace = config_provider()
        self._rsg: IRelationalStorageGateway = rsg_provider()

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:
        if not isinstance(self._rsg, SQLAlchemyRelationalStorageGateway):
            raise RuntimeError("Admin requires SQLAlchemyRelationalStorageGateway")

        app = cors(app, allow_origin=self._config.acp.cors_origins)

        registry: IAdminRegistry = AdminRegistry(strict_permission_decls=True)
        di.container.register_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY, registry)

        contribute_all(registry=registry, mugen_cfg=self._config.dict)
        AdminRuntimeBinder(registry=registry, rsg=self._rsg).bind_all()
        registry.freeze()

        di.container.register_ext_service(
            di.EXT_SERVICE_ADMIN_SVC_JWT,
            EdDsaJwtService(),
        )
        di.container.register_ext_service(
            di.EXT_SERVICE_ADMIN_SVC_AUTH,
            AuthorizationService(),
        )

        # Import endpoints now that services are available.
        # pylint: disable=import-outside-toplevel
        # pylint: disable=unused-import
        import mugen.core.plugin.acp.api
