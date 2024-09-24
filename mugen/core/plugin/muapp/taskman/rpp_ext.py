"""Provides an implementation of IRPPExtension to manage task indicators."""

__all__ = ["MuAppTaskmanRPPExtension"]

from dependency_injector import providers
from dependency_injector.wiring import inject, Provide

from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.di import DIContainer


# pylint: disable=too-few-public-methods
class MuAppTaskmanRPPExtension(IRPPExtension):
    """An implementation of IRPPExtension to manage task indicators."""

    @inject
    def __init__(
        self,
        config: providers.Configuration = Provide[  # pylint: disable=c-extension-no-member
            DIContainer.config.delegate()
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway

    @property
    def platforms(self) -> list[str]:
        return []

    async def preprocess_response(
        self,
        response: str,
        user_id: str,
    ) -> tuple[str, bool, bool]:
        task = False
        end_task = False
        # Check for start task indicator.
        if "[task]" in response:
            self._logging_gateway.debug("[task] detected.")
            task = True
            response = response.replace("[task]", "").strip()

        # Check for end task indicator.
        if "[end-task]" in response:
            self._logging_gateway.debug("[end-task] detected.")
            end_task = True
            response = response.replace("[end-task]", "").strip()
            if response == "":
                response = f"{self._config.matrix.assistant.name().split(" ")[0]} out."

        return (response, task, end_task)
