"""Provides a SambaNova chat completion gateway."""

# https://community.sambanova.ai/t/create-chat-completion-api/105

from io import BytesIO
import json
import traceback
from types import SimpleNamespace
from typing import Any

from dependency_injector import providers
import pycurl

from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class SambaNovaCompletionGateway(ICompletionGateway):
    """A SambaNova chat compeltion gateway."""

    def __init__(
        self,
        config: providers.Configuration,  # pylint: disable=c-extension-no-member
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        context: list[dict],
        operation: str = "completion",
    ) -> SimpleNamespace | None:
        model = self._config.sambanova.api()[operation]["model"]
        _temperature = float(self._config.sambanova.api()[operation]["temp"])

        response = None
        try:
            headers: list[str] = [
                f"Authorization: Basic {self._config.sambanova.api.key()}",
                "Content-Type: application/json",
            ]
            data: dict[str, Any] = {
                "messages": context,
                "stop": ["<|eot_id|>"],
                "model": model,
                "stream": True,
                "stream_options": {
                    "include_usage": False,
                },
            }

            buffer = BytesIO()

            # pylint: disable=c-extension-no-member
            c = pycurl.Curl()
            c.setopt(c.URL, self._config.sambanova.api.endpoint())
            c.setopt(c.POSTFIELDS, json.dumps(data))
            c.setopt(c.HTTPHEADER, headers)
            c.setopt(c.WRITEFUNCTION, buffer.write)
            c.setopt(pycurl.SSL_VERIFYPEER, 1)
            c.setopt(pycurl.SSL_VERIFYHOST, 2)
            c.setopt(pycurl.CAINFO, "/etc/ssl/certs/ca-certificates.crt")
            c.perform()
            c.close()

            chunks = [
                x.replace("data: ", "")
                for x in buffer.getvalue().decode("utf8").strip().split("\n\n")
            ]

            message: str = ""
            if len(chunks) == 1:
                print(chunks)
                json_data = json.loads(chunks[0])
                if "type" in json_data.keys():
                    message += json_data["type"]
            else:
                for chunk in chunks:
                    if chunk != "[DONE]":
                        json_data = json.loads(chunk)
                        if "choices" in json_data.keys():
                            if json_data["choices"][0]["finish_reason"] is None:
                                message += json_data["choices"][0]["delta"]["content"]
                        else:
                            if "error" in json_data.keys():
                                message += json_data["error"]["type"]

            response = SimpleNamespace()
            response.content = message
        except json.JSONDecodeError:
            traceback.print_exc()

        return response
