"""Unit tests for mugen.core.gateway.completion.azure_foundry."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.gateway.completion import (
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
)
from mugen.core.gateway.completion.azure_foundry import AzureFoundryCompletionGateway
from mugen.core.gateway.completion.openai import OpenAICompletionGateway


def _make_config(
    *,
    key: object = "azure-key",
    base_url: object = "https://example.services.ai.azure.com/models",
    version: object = "2025-04-01-preview",
    timeout_seconds: object = 30.0,
) -> SimpleNamespace:
    operation_cfg = {
        "model": "gpt-4.1-mini",
        "temp": 0.1,
        "top_p": 0.8,
    }
    return SimpleNamespace(
        mugen=SimpleNamespace(environment="development"),
        azure=SimpleNamespace(
            foundry=SimpleNamespace(
                api=SimpleNamespace(
                    key=key,
                    base_url=base_url,
                    version=version,
                    timeout_seconds=timeout_seconds,
                    dict={
                        "classification": dict(operation_cfg),
                        "completion": dict(operation_cfg),
                    },
                )
            )
        ),
    )


class TestMugenGatewayCompletionAzureFoundry(unittest.IsolatedAsyncioTestCase):
    """Covers Azure AI Foundry adapter behavior around OpenAI gateway internals."""

    def test_init_builds_client_with_api_key_header_version_and_timeout(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ) as openai_async_openai,
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ) as foundry_async_openai,
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

        openai_async_openai.assert_called_once_with(
            api_key="azure-key",
            base_url="https://example.services.ai.azure.com/models",
            timeout=30.0,
        )
        foundry_async_openai.assert_called_once_with(
            api_key="azure-key",
            base_url="https://example.services.ai.azure.com/models",
            default_headers={"api-key": "azure-key"},
            default_query={"api-version": "2025-04-01-preview"},
            timeout=30.0,
        )

    def test_init_omits_optional_version_and_timeout_when_not_set(self) -> None:
        config = _make_config(version="   ", timeout_seconds=None)
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ) as openai_async_openai,
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ) as foundry_async_openai,
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

        openai_async_openai.assert_called_once_with(
            api_key="azure-key",
            base_url="https://example.services.ai.azure.com/models",
        )
        foundry_async_openai.assert_called_once_with(
            api_key="azure-key",
            base_url="https://example.services.ai.azure.com/models",
            default_headers={"api-key": "azure-key"},
        )

    def test_init_handles_non_string_version(self) -> None:
        config = _make_config(version=None, timeout_seconds=None)
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ) as foundry_async_openai,
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

        foundry_async_openai.assert_called_once_with(
            api_key="azure-key",
            base_url="https://example.services.ai.azure.com/models",
            default_headers={"api-key": "azure-key"},
        )

    def test_init_requires_azure_foundry_api_section(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(environment="development"),
            azure=SimpleNamespace(foundry=SimpleNamespace()),
        )
        logging_gateway = Mock()

        with self.assertRaisesRegex(
            RuntimeError,
            "azure.foundry.api section is required",
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

    def test_init_requires_key(self) -> None:
        config = _make_config(key="   ")
        logging_gateway = Mock()

        with self.assertRaisesRegex(
            RuntimeError,
            "azure.foundry.api.key is required",
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

    def test_init_requires_base_url(self) -> None:
        config = _make_config(base_url="")
        logging_gateway = Mock()

        with self.assertRaisesRegex(
            RuntimeError,
            "azure.foundry.api.base_url is required",
        ):
            AzureFoundryCompletionGateway(config, logging_gateway)

    async def test_get_completion_maps_openai_surface_vendor_param(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
        ):
            gateway = AzureFoundryCompletionGateway(config, logging_gateway)

        completion_response = CompletionResponse(content="ok")
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"openai_api": "responses"},
        )

        with patch.object(
            OpenAICompletionGateway,
            "get_completion",
            AsyncMock(return_value=completion_response),
        ) as parent_get_completion:
            response = await gateway.get_completion(request)

        self.assertIs(response, completion_response)
        self.assertEqual(parent_get_completion.await_count, 1)
        delegated_request = parent_get_completion.await_args.args[0]
        self.assertEqual(delegated_request.vendor_params["openai_api"], "responses")
        self.assertEqual(
            delegated_request.vendor_params["azure_foundry_api"],
            "responses",
        )

    async def test_get_completion_preserves_existing_azure_surface_vendor_param(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
        ):
            gateway = AzureFoundryCompletionGateway(config, logging_gateway)

        completion_response = CompletionResponse(content="ok")
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={
                "openai_api": "responses",
                "azure_foundry_api": "chat_completions",
            },
        )

        with patch.object(
            OpenAICompletionGateway,
            "get_completion",
            AsyncMock(return_value=completion_response),
        ) as parent_get_completion:
            response = await gateway.get_completion(request)

        self.assertIs(response, completion_response)
        self.assertEqual(parent_get_completion.await_args.args[0], request)

    async def test_get_completion_passthrough_when_openai_alias_is_absent(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.completion.openai.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
            patch(
                "mugen.core.gateway.completion.azure_foundry.AsyncOpenAI",
                return_value=SimpleNamespace(),
            ),
        ):
            gateway = AzureFoundryCompletionGateway(config, logging_gateway)

        completion_response = CompletionResponse(content="ok")
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={},
        )

        with patch.object(
            OpenAICompletionGateway,
            "get_completion",
            AsyncMock(return_value=completion_response),
        ) as parent_get_completion:
            response = await gateway.get_completion(request)

        self.assertIs(response, completion_response)
        self.assertEqual(parent_get_completion.await_args.args[0], request)
