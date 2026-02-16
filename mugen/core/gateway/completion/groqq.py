"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

from types import SimpleNamespace
from typing import Any

from groq import AsyncGroq, GroqError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
    normalise_completion_request,
)
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat completion gateway."""

    _env_prefix = "groq"
    _provider = "groq"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._api = AsyncGroq(api_key=self._config.groq.api.key)
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        request: CompletionRequest | list[dict[str, Any]],
        operation: str = "completion",
    ) -> CompletionResponse:
        completion_request = normalise_completion_request(request, operation=operation)
        operation_config = self._resolve_operation_config(completion_request.operation)

        model = completion_request.model or operation_config["model"]
        temperature = completion_request.inference.temperature
        if temperature is None:
            temperature = float(operation_config.get("temp", 0.0))

        top_p = completion_request.inference.top_p
        if top_p is None:
            top_p = float(operation_config.get("top_p", 1.0))

        payload_messages = [
            message.to_dict() for message in completion_request.messages
        ]
        kwargs: dict[str, Any] = {
            "messages": payload_messages,
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }
        if completion_request.inference.stop:
            kwargs["stop"] = completion_request.inference.stop
        if completion_request.inference.max_tokens is not None:
            kwargs["max_tokens"] = completion_request.inference.max_tokens

        extra_keys = [
            "frequency_penalty",
            "presence_penalty",
            "response_format",
            "seed",
            "tool_choice",
            "tools",
            "user",
        ]
        for key in extra_keys:
            if key in completion_request.vendor_params:
                kwargs[key] = completion_request.vendor_params[key]

        try:
            chat_completion = await self._api.chat.completions.create(**kwargs)
            choice = chat_completion.choices[0]
            content = choice.message.content
            usage = self._usage_from_response(chat_completion)
            return CompletionResponse(
                content=content if isinstance(content, str) else "",
                model=getattr(chat_completion, "model", model),
                stop_reason=getattr(choice, "finish_reason", None),
                usage=usage,
                raw=chat_completion,
            )
        except GroqError as e:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_completion: "
                "An error was encountered while trying the Groq API."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=str(e),
                cause=e,
            ) from e
        except CompletionGatewayError:
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_completion: "
                "Unexpected failure while processing completion request."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Unexpected Groq completion failure.",
                cause=e,
            ) from e

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.groq.api.dict[operation]
        except (AttributeError, KeyError) as e:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Groq operation configuration: {operation}",
                cause=e,
            ) from e

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Groq operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Groq operation '{operation}' is missing model.",
            )

        return cfg

    @staticmethod
    def _usage_from_response(chat_completion: Any) -> CompletionUsage | None:
        usage = getattr(chat_completion, "usage", None)
        if usage is None:
            return None

        return CompletionUsage(
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
