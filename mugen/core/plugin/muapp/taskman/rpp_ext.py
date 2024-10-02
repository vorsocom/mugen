"""Provides an implementation of IRPPExtension to manage task indicators."""

__all__ = ["MuAppTaskmanRPPExtension"]

from dependency_injector import providers
from dependency_injector.wiring import inject, Provide

from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.di import DIContainer


# pylint: disable=too-few-public-methods
class MuAppTaskmanRPPExtension(IRPPExtension):
    """An implementation of IRPPExtension to manage task indicators."""

    @inject
    def __init__(
        self,
        completion_gateway: ICompletionGateway = Provide[
            DIContainer.completion_gateway
        ],
        config: providers.Configuration = Provide[  # pylint: disable=c-extension-no-member
            DIContainer.config.delegate()
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
        messaging_service: IMessagingService = Provide[DIContainer.messaging_service],
    ) -> None:
        self._completion_gateway = completion_gateway
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
    ) -> str:
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
            elif (
                assistant_response == ""
                and self._config.muapp.taskman.empty_response_text() == ""
            ):
                self._logging_gateway.debug("Generating end of task response.")
                completion = await self._completion_gateway.get_completion(
                    context=thread["messages"][:-1]
                    + [
                        {
                            "role": "system",
                            "content": (
                                "Your conversation with the user has ended. Let them"
                                " know this and that they can reach out to you if they"
                                " need assistance with anything else. They do not have"
                                " to respond to your message."
                            ),
                        }
                    ]
                )

                assistant_response = completion.content
                thread["messages"][-1]["content"] = assistant_response

        if task:
            thread["messages"][-1] = {
                "role": "system",
                "content": "A task is ongoing.",
            }
            thread["messages"].append(
                {"role": "assistant", "content": assistant_response}
            )
            thread["messages"] = thread["messages"][-3:]
        elif end_task:
            thread["messages"][-1]["content"] = assistant_response

            if not self._messaging_service.trigger_in_response(assistant_response):
                thread["messages"] = thread["messages"][-2:]

        self._messaging_service.save_attention_thread(room_id, thread)
        return assistant_response
