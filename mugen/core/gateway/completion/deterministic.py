"""Deterministic completion gateway for CI/local test runs."""

from __future__ import annotations

from types import SimpleNamespace

from mugen.core.contract.gateway.completion import (
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.message_serialization import (
    serialize_completion_message_content,
)


class DeterministicCompletionGateway(ICompletionGateway):
    """A no-network completion gateway with deterministic responses."""

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

    async def check_readiness(self) -> None:
        _ = self._config
        _ = self._logging_gateway

    async def aclose(self) -> None:
        return None

    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        content = self._resolve_content(request)
        model = request.model or "deterministic-model"

        return CompletionResponse(
            content=content,
            model=model,
            stop_reason="stop",
            message={"role": "assistant", "content": content},
            usage=CompletionUsage(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                vendor_fields={"provider": "deterministic"},
            ),
            raw={
                "provider": "deterministic",
                "operation": request.operation,
                "message_count": len(request.messages),
            },
        )

    @staticmethod
    def _resolve_content(request: CompletionRequest) -> str:
        override = request.vendor_params.get("deterministic_content")
        if isinstance(override, str):
            return override

        for message in reversed(request.messages):
            if message.role != "user":
                continue
            if isinstance(message.content, str) and message.content.strip() != "":
                return message.content
            if isinstance(message.content, dict) and message.content:
                return serialize_completion_message_content(message.content)
            if isinstance(message.content, list) and message.content:
                return serialize_completion_message_content(message.content)

        return "ok"
