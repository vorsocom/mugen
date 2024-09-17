"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

import traceback
from types import SimpleNamespace

from groq import AsyncGroq, GroqError
from groq.types.chat import ChatCompletionMessage

from mugen.core.contract.completion_gateway import ICompletionGateway
from mugen.core.contract.logging_gateway import ILoggingGateway


# pylint: disable=too-few-public-methods
class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat compeltion gateway."""

    _env_prefix = "groq"

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
        operation: str = "completion",
    ) -> ChatCompletionMessage | None:
        model = self._config.__dict__[f"{self._env_prefix}_api_{operation}_model"]
        temperature = float(
            self._config.__dict__[f"{self._env_prefix}_api_{operation}_temp"]
        )

        response = None
        # self._logging_gateway.debug(context)
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context,
                model=model,
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
