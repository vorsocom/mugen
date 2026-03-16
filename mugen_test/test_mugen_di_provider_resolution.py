"""Unit tests for deterministic provider token resolution in mugen.core.di."""

from types import SimpleNamespace
import unittest

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.sms import ISMSGateway


# pylint: disable=protected-access
class TestDIProviderResolution(unittest.TestCase):
    """Unit tests for tokenized provider resolution rules."""

    def test_resolve_provider_class_rejects_module_class_and_unknown_token(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={
                    "mugen": {"modules": {"core": {"gateway": {"completion": None}}}}
                },
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={
                    "mugen": {
                        "modules": {
                            "core": {"gateway": {"completion": "module.path:Gateway"}}
                        }
                    }
                },
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={
                    "mugen": {
                        "modules": {
                            "core": {"gateway": {"completion": "unknown-token"}}
                        }
                    }
                },
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )

    def test_completion_provider_uses_configured_token(self) -> None:
        """Build completion provider from explicit token configuration."""
        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "deterministic",
                        }
                    }
                }
            }
        }
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(
                twilio=SimpleNamespace(
                    api=SimpleNamespace(
                        account_sid="AC123",
                        auth_token="auth-token",
                        api_key_sid="",
                        api_key_secret="",
                        base_url="https://api.twilio.com",
                        timeout_seconds=10.0,
                    ),
                    messaging=SimpleNamespace(
                        default_from="+15550000001",
                        messaging_service_sid="",
                    ),
                )
            ),
            logging_gateway=unittest.mock.Mock(),
        )

        di._build_provider(config, injector, provider_name="completion_gateway")

        self.assertEqual(
            type(injector.completion_gateway).__name__, "DeterministicCompletionGateway"
        )

    def test_sms_provider_uses_configured_token(self) -> None:
        """Build SMS provider from explicit token configuration."""
        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "sms": "twilio",
                        }
                    }
                }
            }
        }
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(
                twilio=SimpleNamespace(
                    api=SimpleNamespace(
                        account_sid="AC123",
                        auth_token="auth-token",
                        api_key_sid="",
                        api_key_secret="",
                        base_url="https://api.twilio.com",
                        timeout_seconds=10.0,
                    ),
                    messaging=SimpleNamespace(
                        default_from="+15550000001",
                        messaging_service_sid="",
                    ),
                )
            ),
            logging_gateway=unittest.mock.Mock(),
        )

        di._build_provider(config, injector, provider_name="sms_gateway")

        self.assertIsInstance(injector.sms_gateway, ISMSGateway)
