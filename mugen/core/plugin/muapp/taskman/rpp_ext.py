"""Provides an implementation of IRPPExtension to manage task indicators."""

__all__ = ["MuAppTaskmanRPPExtension"]

from dependency_injector import providers
from dependency_injector.wiring import inject, Provide

from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService
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
        messaging_service: IMessagingService = Provide[DIContainer.messaging_service],
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service

    @property
    def platforms(self) -> list[str]:
        return []

    async def preprocess_response(
        self,
        room_id: str,
        user_id: str,
    ) -> tuple[str, bool, bool]:
        task = False
        end_task = False
        thread = self._messaging_service.load_attention_thread(room_id)
        assistant_response = thread["messages"][-1]["content"]

        # Check for start task indicator.
        if "[task]" in assistant_response:
            self._logging_gateway.debug("[task] detected.")
            task = True
            assistant_response = assistant_response.replace("[task]", "").strip()

        # Check for end task indicator.
        if "[end-task]" in assistant_response:
            self._logging_gateway.debug("[end-task] detected.")
            end_task = True
            assistant_response = assistant_response.replace("[end-task]", "").strip()

            if (
                assistant_response == ""
                and self._config.muapp.taskman.empty_response_text() != ""
            ):
                assistant_response = self._config.muapp.taskman.empty_response_text()

        if task:
            thread["messages"][-1] = {
                "role": "system",
                "content": "A task is ongoing.",
            }
            thread["messages"].append(
                {"role": "assistant", "content": assistant_response}
            )
        else:
            thread["messages"][-1]["content"] = assistant_response

        self._messaging_service.save_attention_thread(room_id, thread)
        return (assistant_response, task, end_task)
