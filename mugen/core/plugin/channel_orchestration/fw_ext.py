"""Provides an implementation of IFWExtension for the channel_orchestration plugin."""

__all__ = ["ChannelOrchestrationFWExtension"]

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)
from mugen.core.plugin.channel_orchestration.model import HumanHandoffSession
from mugen.core.plugin.channel_orchestration.service import HumanHandoffSessionService

_HUMAN_HANDOFF_TABLE = "channel_orchestration_human_handoff_session"


def _rsg_provider():
    return di.container.relational_storage_gateway


class ChannelOrchestrationFWExtension(
    IFWExtension
):  # pylint: disable=too-few-public-methods
    """Framework extension for the channel_orchestration plugin."""

    def __init__(
        self,
        rsg_provider=_rsg_provider,
    ) -> None:
        self._rsg: IRelationalStorageGateway = rsg_provider()

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        self._register_runtime_tables()
        handoff_service = HumanHandoffSessionService(
            table=_HUMAN_HANDOFF_TABLE,
            rsg=self._rsg,
        )
        di.container.register_ext_service(
            di.EXT_SERVICE_HUMAN_HANDOFF,
            handoff_service,
            override=True,
        )

        # Import endpoints (currently none beyond ACP generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.channel_orchestration.api  # noqa: F401

    def _register_runtime_tables(self) -> None:
        if not isinstance(self._rsg, SQLAlchemyRelationalStorageGateway):
            return
        try:
            self._rsg.register_tables(
                {_HUMAN_HANDOFF_TABLE: HumanHandoffSession.__table__}
            )
        except ValueError:
            return
