"""Provides a CRUD service for channel profiles."""

__all__ = ["ChannelProfileService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.channel_profile import (
    IChannelProfileService,
)
from mugen.core.plugin.channel_orchestration.domain import ChannelProfileDE


class ChannelProfileService(  # pylint: disable=too-few-public-methods
    IRelationalService[ChannelProfileDE],
    IChannelProfileService,
):
    """A CRUD service for channel profiles."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ChannelProfileDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
