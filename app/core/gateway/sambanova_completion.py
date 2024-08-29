"""Provides a SambaNova chat completion gateway."""

# https://community.sambanova.ai/t/create-chat-completion-api/105

from io import BytesIO
import json
import traceback
from types import SimpleNamespace

import pycurl

from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.logging_gateway import ILoggingGateway


class SambaNovaCompletionGateway(ICompletionGateway):
    """A SambaNova chat compeltion gateway."""

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = SimpleNamespace(**config)
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        context: list[dict],
        model: str,
        response_format: str = "text",
        temperature: float = 1,
    ) -> SimpleNamespace | None:
        response = None
        # self._logging_gateway.debug(context)
        try:
            headers = [
                f"Authorization: Basic {self._config.sambanova_api_key}",
                "Content-Type: application/json",
            ]
            data = {
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
            c.setopt(c.URL, self._config.sambanova_api_endpoint)
            c.setopt(c.POSTFIELDS, json.dumps(data))
            c.setopt(c.HTTPHEADER, headers)
            c.setopt(c.WRITEDATA, buffer)
            c.setopt(pycurl.SSL_VERIFYPEER, 1)
            c.setopt(pycurl.SSL_VERIFYHOST, 2)
            c.setopt(pycurl.CAINFO, "/etc/ssl/certs/ca-certificates.crt")
            c.perform()
            c.close()

            c_response = buffer.getvalue()
            decoded = c_response.decode("utf8")
            chunks = [
                json.loads(x.replace("data: ", ""))["choices"]
                for x in decoded.split("\n\n")
                if x.replace("data: ", "") not in ["", "[DONE]"]
                and "choices" in json.loads(x.replace("data: ", "")).keys()
            ]

            message = "".join(
                [x[0]["delta"]["content"] for x in chunks if x[0]["delta"] != {}]
            )

            response = SimpleNamespace()
            response.content = message
        except json.JSONDecodeError:
            traceback.print_exc()

        return response
