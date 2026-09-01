"""Runtime wiring for the Core Service Profile capability."""

from __future__ import annotations

__all__ = ["ServiceProfileFWExtension"]

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.service_profile.service import (
    DefaultServiceProfileEntitlementService,
    DefaultServiceProfileResolver,
)


def _rsg_provider():
    return di.container.relational_storage_gateway


def _logging_provider():
    return di.container.logging_gateway


class ServiceProfileFWExtension(IFWExtension):
    """Validate dependencies and register Service Profile runtime services."""

    _REQUIRED_ENTITY_SETS = (
        "IngressBindings",
        "BillingAccounts",
        "BillingSubscriptions",
        "BillingPrices",
        "BillingProducts",
        "KnowledgeScopes",
        "ServiceProfiles",
        "ServiceProfileIngressBindings",
        "ServiceProfileSubscriptions",
    )

    def __init__(
        self,
        rsg_provider=_rsg_provider,
        logging_provider=_logging_provider,
    ) -> None:
        self._rsg: IRelationalStorageGateway = rsg_provider()
        self._logging_gateway: ILoggingGateway = logging_provider()

    @property
    def platforms(self) -> list[str]:
        return []

    @classmethod
    def _validate_registry(cls, registry: IAdminRegistry) -> None:
        missing: list[str] = []
        for entity_set in cls._REQUIRED_ENTITY_SETS:
            try:
                resource = registry.get_resource(entity_set)
                registry.get_edm_service(resource.service_key)
            except KeyError:
                missing.append(entity_set)
        if missing:
            raise RuntimeError(
                "Service Profile requires enabled ACP, Channel Orchestration, and "
                "Billing resources; unavailable entity sets: " + ", ".join(missing)
            )

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        if not isinstance(self._rsg, SQLAlchemyRelationalStorageGateway):
            raise RuntimeError(
                "Service Profile requires SQLAlchemyRelationalStorageGateway."
            )
        try:
            registry: IAdminRegistry = di.container.get_required_ext_service(
                di.EXT_SERVICE_ADMIN_REGISTRY
            )
        except KeyError as exc:
            raise RuntimeError(
                "Service Profile requires the ACP framework extension to be ready."
            ) from exc
        self._validate_registry(registry)
        di.container.register_ext_services(
            {
                di.EXT_SERVICE_SERVICE_PROFILE_RESOLVER: (
                    DefaultServiceProfileResolver(
                        rsg=self._rsg,
                        logging_gateway=self._logging_gateway,
                    )
                ),
                di.EXT_SERVICE_SERVICE_PROFILE_ENTITLEMENT: (
                    DefaultServiceProfileEntitlementService(
                        rsg=self._rsg,
                        logging_gateway=self._logging_gateway,
                    )
                ),
            },
            override=True,
        )

        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.service_profile.api  # noqa: F401
