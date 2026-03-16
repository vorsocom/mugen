"""Provides an Azure AI Foundry completion gateway."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI

from mugen.core.contract.gateway.completion import CompletionRequest, CompletionResponse
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.openai import OpenAICompletionGateway


# pylint: disable=too-few-public-methods
class AzureFoundryCompletionGateway(OpenAICompletionGateway):
    """An Azure AI Foundry completion gateway using OpenAI-compatible payloads."""

    _provider = "azure_foundry"
    _surface_vendor_param = "azure_foundry_api"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        api_cfg = self._resolve_api_config(config)
        api_key = self._require_non_empty_string(api_cfg, "key")
        base_url = self._require_non_empty_string(api_cfg, "base_url")
        api_version = self._normalize_optional_string(getattr(api_cfg, "version", None))

        adapted_config = self._build_openai_compatible_config(
            config=config,
            api_cfg=api_cfg,
            api_key=api_key,
            base_url=base_url,
        )
        super().__init__(adapted_config, logging_gateway)

        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "default_headers": {"api-key": api_key},
        }
        if api_version is not None:
            client_kwargs["default_query"] = {"api-version": api_version}
        if self._timeout_seconds is not None:
            client_kwargs["timeout"] = self._timeout_seconds

        self._api = AsyncOpenAI(**client_kwargs)

    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        completion_request = request
        if (
            "openai_api" in request.vendor_params
            and self._surface_vendor_param not in request.vendor_params
        ):
            vendor_params = dict(request.vendor_params)
            vendor_params[self._surface_vendor_param] = vendor_params["openai_api"]
            completion_request = replace(request, vendor_params=vendor_params)

        return await super().get_completion(completion_request)

    @staticmethod
    def _resolve_api_config(config: SimpleNamespace) -> Any:
        foundry_cfg = getattr(
            getattr(config, "azure", SimpleNamespace()),
            "foundry",
            None,
        )
        api_cfg = getattr(foundry_cfg, "api", None)
        if api_cfg is None:
            raise RuntimeError(
                "Invalid configuration: azure.foundry.api section is required."
            )
        return api_cfg

    @staticmethod
    def _require_non_empty_string(api_cfg: Any, key: str) -> str:
        raw_value = getattr(api_cfg, key, None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: azure.foundry.api.{key} is required."
            )
        return raw_value.strip()

    @staticmethod
    def _normalize_optional_string(raw_value: Any) -> str | None:
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    @staticmethod
    def _build_openai_compatible_config(
        *,
        config: SimpleNamespace,
        api_cfg: Any,
        api_key: str,
        base_url: str,
    ) -> SimpleNamespace:
        adapted = SimpleNamespace(**vars(config))
        adapted.openai = SimpleNamespace(
            api=SimpleNamespace(
                key=api_key,
                base_url=base_url,
                timeout_seconds=getattr(api_cfg, "timeout_seconds", None),
                dict=getattr(api_cfg, "dict", {}),
            )
        )
        return adapted
