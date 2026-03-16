"""Provides a service contract for ChannelProfileDE-related services."""

__all__ = ["IChannelProfileService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import ChannelProfileDE


class IChannelProfileService(ICrudService[ChannelProfileDE], ABC):
    """A service contract for ChannelProfileDE-related services."""
