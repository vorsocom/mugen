"""Provides a CRUD contract for Service Profile ingress assignments."""

__all__ = ["IServiceProfileIngressBindingService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.service_profile.domain import ServiceProfileIngressBindingDE


class IServiceProfileIngressBindingService(
    ICrudService[ServiceProfileIngressBindingDE],
    ABC,
):
    """A service contract for Service Profile ingress assignment CRUD."""
