"""Unit tests for shared completion sampling-control helpers."""

import unittest

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.sampling_controls import (
    resolve_sampling_controls_enabled,
    resolve_sampling_parameter_kwargs,
)


def _request(
    *,
    temperature: float | None = None,
    top_p: float | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
        inference=CompletionInferenceConfig(temperature=temperature, top_p=top_p),
    )


class TestMugenGatewayCompletionSamplingControls(unittest.TestCase):
    """Covers shared sampling-control parsing and value resolution."""

    def test_resolve_sampling_controls_enabled_accepts_supported_values(self) -> None:
        request = _request()
        for value in [None, "", "enabled", "ENABLED", " enabled "]:
            with self.subTest(value=value):
                self.assertTrue(
                    resolve_sampling_controls_enabled(
                        request=request,
                        operation_config={"sampling_controls": value},
                        provider="provider",
                        provider_label="ProviderGateway",
                    )
                )

        self.assertFalse(
            resolve_sampling_controls_enabled(
                request=request,
                operation_config={"sampling_controls": "disabled"},
                provider="provider",
                provider_label="ProviderGateway",
            )
        )

    def test_resolve_sampling_controls_enabled_rejects_invalid_values(self) -> None:
        request = _request()
        for value in [1, "auto"]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    CompletionGatewayError,
                    "ProviderGateway: Invalid sampling_controls value",
                ) as context:
                    resolve_sampling_controls_enabled(
                        request=request,
                        operation_config={"sampling_controls": value},
                        provider="provider",
                        provider_label="ProviderGateway",
                        timeout_applied=2.5,
                    )
                self.assertEqual(context.exception.provider, "provider")
                self.assertEqual(context.exception.operation, "completion")
                self.assertEqual(context.exception.timeout_applied, 2.5)

    def test_resolve_sampling_parameter_kwargs_uses_request_values_first(self) -> None:
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(temperature=0.7, top_p=0.6),
                operation_config={"temp": "0.1", "top_p": "0.2"},
                provider="provider",
                provider_label="ProviderGateway",
            ),
            {"temperature": 0.7, "top_p": 0.6},
        )

    def test_resolve_sampling_parameter_kwargs_uses_config_and_custom_keys(
        self,
    ) -> None:
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(),
                operation_config={"temp": "0.1", "top_p": "0.2"},
                provider="provider",
                provider_label="ProviderGateway",
                top_p_key="topP",
            ),
            {"temperature": 0.1, "topP": 0.2},
        )

    def test_resolve_sampling_parameter_kwargs_uses_defaults_and_disabled(self) -> None:
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(),
                operation_config={},
                provider="provider",
                provider_label="ProviderGateway",
                default_temperature=0.0,
                default_top_p=1.0,
            ),
            {"temperature": 0.0, "top_p": 1.0},
        )
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(temperature=0.7, top_p=0.6),
                operation_config={"sampling_controls": "disabled"},
                provider="provider",
                provider_label="ProviderGateway",
                default_temperature=0.0,
                default_top_p=1.0,
            ),
            {},
        )

    def test_resolve_sampling_parameter_kwargs_can_skip_top_p_config(self) -> None:
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(top_p=0.8),
                operation_config={"temp": "0.1", "top_p": "0.2"},
                provider="provider",
                provider_label="ProviderGateway",
                config_top_p_key=None,
            ),
            {"temperature": 0.1, "top_p": 0.8},
        )
        self.assertEqual(
            resolve_sampling_parameter_kwargs(
                request=_request(),
                operation_config={"top_p": "0.2"},
                provider="provider",
                provider_label="ProviderGateway",
                config_temperature_key=None,
                config_top_p_key=None,
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
