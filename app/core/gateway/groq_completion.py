"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

import traceback
from types import SimpleNamespace

from groq import AsyncGroq, GroqError
from groq.types.chat import ChatCompletionMessage

from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.logging_gateway import ILoggingGateway


# pylint: disable=too-few-public-methods
class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat compeltion gateway."""

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = SimpleNamespace(**config)
        self._api = AsyncGroq(api_key=self._config.groq_api_key)
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        context: list[dict],
        model: str,
        response_format: str = "text",
        temperature: float = 1,
    ) -> ChatCompletionMessage | None:
        response = None
        # self._logging_gateway.debug(context)
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context,
                model=model,
                response_format={"type": response_format},
                temperature=temperature,
                top_p=1,
                stream=False,
                stop=None,
            )
            response = chat_completion.choices[0].message
        except GroqError:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_completion: An error was encountered while"
                " trying the Groq API."
            )
            traceback.print_exc()

        return response
