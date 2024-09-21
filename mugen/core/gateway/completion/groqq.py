"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

import traceback
from typing import Any

from dependency_injector import providers
from groq import AsyncGroq, GroqError

from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat compeltion gateway."""

    _env_prefix = "groq"

    def __init__(
        self,
        config: providers.Configuration,  # pylint: disable=c-extension-no-member
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._api = AsyncGroq(api_key=self._config.groq.api.key())
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        context: list[dict],
        operation: str = "completion",
    ) -> Any | None:
        model = self._config.aws.bedrock.api()[operation]["model"]
        temperature = float(self._config.aws.bedrock.api()[operation]["temp"])

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
