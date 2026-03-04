"""Edge-branch unit tests for mugen.core.di helper routines."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


# pylint: disable=protected-access
class TestMugenDIEdgeBranches(unittest.TestCase):
    """Exercise remaining branch-heavy DI helpers."""

    @staticmethod
    def _runtime_section(
        *,
        profile: object = "platform_full",
        provider_readiness_timeout_seconds: object = 1.0,
        provider_shutdown_timeout_seconds: object = 10.0,
        shutdown_timeout_seconds: object = 60.0,
        startup_timeout_seconds: object = 30.0,
    ) -> dict:
        return {
            "profile": profile,
            "provider_readiness_timeout_seconds": provider_readiness_timeout_seconds,
            "provider_shutdown_timeout_seconds": provider_shutdown_timeout_seconds,
            "shutdown_timeout_seconds": shutdown_timeout_seconds,
            "phase_b": {
                "startup_timeout_seconds": startup_timeout_seconds,
            },
        }

    @staticmethod
    def _readiness_config(
        *,
        profile: str = "platform_full",
        platforms: list[str] | None = None,
        include_relational: bool = False,
        include_media: bool = False,
    ) -> dict:
        config: dict = {
            "mugen": {
                "runtime": TestMugenDIEdgeBranches._runtime_section(
                    profile=profile,
                ),
                "platforms": [] if platforms is None else platforms,
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "deterministic",
                            "storage": {
                                "keyval": "relational",
                            }
                        }
                    }
                },
            }
        }
        if include_relational:
            config["mugen"]["modules"]["core"]["gateway"]["storage"]["relational"] = (  # type: ignore[index]
                "sqlalchemy"
            )
        if include_media:
            config["mugen"]["modules"]["core"]["gateway"]["storage"]["media"] = (  # type: ignore[index]
                "default"
            )
        return config

    def test_config_path_exists_handles_non_dict_missing_and_present_paths(self) -> None:
        self.assertFalse(di._config_path_exists({"mugen": []}, "mugen", "modules"))
        self.assertFalse(di._config_path_exists({"mugen": {}}, "mugen", "modules"))
        self.assertTrue(di._config_path_exists({"mugen": {"modules": {}}}, "mugen", "modules"))

    def test_config_path_value_returns_none_for_missing_paths(self) -> None:
        self.assertIsNone(di._config_path_value({"mugen": {}}, "mugen", "runtime", "profile"))
        self.assertEqual(
            di._config_path_value({"mugen": {"runtime": {"profile": "platform_full"}}}, "mugen", "runtime", "profile"),
            "platform_full",
        )

    def test_validate_optional_positive_timeout_allows_missing_value(self) -> None:
        di._validate_optional_positive_timeout(None, path="mugen.runtime.some_timeout")
        di._validate_optional_positive_timeout("", path="mugen.runtime.some_timeout")

    def test_get_active_platforms_requires_list(self) -> None:
        self.assertIsNone(di._get_active_platforms({"mugen": {"platforms": "matrix"}}))
        self.assertEqual(di._get_active_platforms({"mugen": {"platforms": ["matrix"]}}), ["matrix"])

    def test_resolve_runtime_profile_override(self) -> None:
        self.assertEqual(
            di._resolve_runtime_profile_override(
                {"mugen": {"runtime": self._runtime_section()}}
            ),
            "platform_full",
        )
        self.assertEqual(
            di._resolve_runtime_profile_override(
                {
                    "mugen": {
                        "runtime": self._runtime_section(),
                        "platforms": ["matrix", "web"],
                    }
                }
            ),
            "platform_full",
        )
        self.assertEqual(
            di._resolve_runtime_profile_override(
                {
                    "mugen": {
                        "runtime": self._runtime_section(),
                        "platforms": ["web"],
                    }
                }
            ),
            "platform_full",
        )
        self.assertEqual(
            di._resolve_runtime_profile_override(
                {
                    "mugen": {
                        "runtime": self._runtime_section(),
                        "platforms": [],
                    }
                }
            ),
            "platform_full",
        )

    def test_resolve_runtime_profile_override_rejects_invalid_override(self) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(
                {"mugen": {"runtime": self._runtime_section(profile="invalid")}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(
                {"mugen": {"runtime": self._runtime_section(profile=""), "platforms": []}}
            )

    def test_normalize_platforms_filters_empty_and_duplicates(self) -> None:
        self.assertEqual(di._normalize_platforms(None), [])
        self.assertEqual(
            di._normalize_platforms([" web ", "", "web", "matrix"]),
            ["web", "matrix"],
        )

    def test_runtime_profile_override_edge_cases(self) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile=None)}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile="   ")}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile="auto")}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile=1)}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile=None)}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": self._runtime_section(profile=None)}}
            )

    def test_validate_container_requires_relational_when_web_platform_is_enabled(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=None,
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            web_client=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": ["web"],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

    def test_validate_container_logs_all_missing_optional_providers(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )
        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "knowledge": "knowledge.module",
                            "email": "email.module",
                        }
                    }
                },
                "runtime": self._runtime_section(),
                "platforms": ["matrix", "whatsapp", "web"],
            }
        }

        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

        injector.logging_gateway.error.assert_any_call("Missing provider (knowledge_gateway).")
        injector.logging_gateway.error.assert_any_call("Missing provider (email_gateway).")
        injector.logging_gateway.error.assert_any_call(
            "Missing provider (web_runtime_store)."
        )
        injector.logging_gateway.error.assert_any_call("Missing provider (matrix_client).")
        injector.logging_gateway.error.assert_any_call("Missing provider (whatsapp_client).")
        injector.logging_gateway.error.assert_any_call("Missing provider (web_client).")

    def test_validate_container_requires_telegram_client_when_platform_active(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": ["telegram"],
            }
        }

        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

        injector.logging_gateway.error.assert_any_call("Missing provider (telegram_client).")

    def test_validate_container_uses_root_logger_when_injector_logger_is_missing(
        self,
    ) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=None,
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": ["matrix"],
            }
        }

        with self.assertLogs("root", level="ERROR") as logs:
            with self.assertRaises(RuntimeError):
                di._validate_container(config, injector)

        self.assertIn("ERROR:root:Missing provider (matrix_client).", logs.output)

    def test_validate_container_accepts_present_optional_knowledge_provider(
        self,
    ) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            knowledge_gateway=object(),
            matrix_client=object(),
        )
        config = {
            "mugen": {
                "modules": {"core": {"gateway": {"knowledge": "knowledge.module"}}},
                "runtime": self._runtime_section(),
                "platforms": ["matrix"],
            }
        }

        di._validate_container(config, injector)

    def test_validate_container_accepts_present_optional_email_provider(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            email_gateway=object(),
            matrix_client=object(),
        )
        config = {
            "mugen": {
                "modules": {"core": {"gateway": {"email": "email.module"}}},
                "runtime": self._runtime_section(),
                "platforms": ["matrix"],
            }
        }

        di._validate_container(config, injector)

    def test_validate_container_rejects_non_platform_full_profile(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            web_client=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(profile="api_only"),
                "platforms": [],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

    def test_validate_container_rejects_non_platform_full_profile_guard(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=logger,
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            matrix_client=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": ["matrix"],
            }
        }

        with patch("mugen.core.di._resolve_runtime_profile_override", return_value="legacy"):
            with self.assertRaisesRegex(RuntimeError, "Runtime profile platform_full is required"):
                di._validate_container(config, injector)

        logger.error.assert_called_with("Runtime profile platform_full is required.")

    def test_validate_container_rejects_web_only_profile(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            web_client=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(profile="web_only"),
                "platforms": ["web"],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

    def test_validate_container_rejects_platform_full_without_platforms(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": [],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

    def test_validate_container_platform_full_without_matrix_platform(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
            whatsapp_client=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": ["whatsapp"],
            }
        }

        di._validate_container(config, injector)

    def test_validate_container_rejects_unknown_platforms(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=logger,
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            relational_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )
        config = {
            "mugen": {
                "runtime": self._runtime_section(),
                "platforms": [" web ", "unknown"],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

        self.assertTrue(
            any(
                call.args[0]
                == "Unsupported platform configuration detected: unknown."
                for call in logger.error.call_args_list
            )
        )

    def test_build_provider_from_spec_handles_attribute_error_when_injector_invalid(
        self,
    ) -> None:
        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config):  # pylint: disable=unused-argument
                pass

        logger = Mock()
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:DummyProvider"}}}

        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            di._build_provider_from_spec(
                config,
                object(),
                spec=spec,
                logger=logger,
            )
        logger.error.assert_called_once_with("Invalid injector (dummy_provider).")

    def test_build_provider_from_spec_skips_warning_when_inactive_message_missing(
        self,
    ) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector()
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
            required_platform="dummy",
            inactive_platform_warning=None,
        )
        config = {"mugen": {"platforms": ["matrix"]}}

        di._build_provider_from_spec(config, injector, spec=spec, logger=logger)

        logger.warning.assert_not_called()

    def test_build_provider_from_spec_normalizes_active_platform_names(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
            required_platform="web",
            inactive_platform_warning="inactive",
        )
        config = {"mugen": {"platforms": [" WEB "], "modules": {"dummy": "dummy.module:Dummy"}}}

        with patch.object(di, "_resolve_provider_class", return_value=Mock()) as resolver:
            di._build_provider_from_spec(
                config,
                injector,
                spec=spec,
                logger=logger,
            )

        resolver.assert_called_once()
        logger.warning.assert_not_called()

    def test_container_proxy_setattr_forwards_non_internal_attrs(self) -> None:
        proxy = di._ContainerProxy()
        target = SimpleNamespace()
        proxy._injector = target
        proxy.some_attribute = "value"
        self.assertEqual(target.some_attribute, "value")

    def test_build_provider_from_spec_strict_required_raises_on_missing_config(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
        )

        with self.assertRaises(di.ProviderBootstrapError):
            di._build_provider_from_spec(
                config={"mugen": {"modules": {"core": {}}}},
                injector=injector,
                spec=spec,
                logger=logger,
                strict_required=True,
            )

    def test_build_provider_from_spec_strict_optional_ignores_missing_config(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())
        spec = di._ProviderSpec(
            provider_name="optional_provider",
            injector_attr="optional_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "optional"),
            constructor_bindings=(("config", "config"),),
            required=False,
        )

        di._build_provider_from_spec(
            config={"mugen": {"modules": {"core": {}}}},
            injector=injector,
            spec=spec,
            logger=logger,
            strict_required=True,
        )
        logger.error.assert_not_called()

    def test_resolve_provider_class_raises_runtime_for_missing_config_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Invalid configuration"):
            di._resolve_provider_class(
                config={},
                provider_name="dummy_provider",
                module_path=("mugen", "modules", "dummy"),
                interface=ICompletionGateway,
            )

    def test_build_provider_from_spec_strict_required_raises_on_invalid_platform_shape(
        self,
    ) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
            required_platform="web",
        )
        with self.assertRaises(di.ProviderBootstrapError):
            di._build_provider_from_spec(
                config={"mugen": {"platforms": "web"}},
                injector=injector,
                spec=spec,
                logger=logger,
                strict_required=True,
            )

    def test_build_provider_from_spec_strict_required_raises_when_resolution_fails(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())
        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:Dummy"}}}
        with patch.object(
            di,
            "_resolve_provider_class",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(di.ProviderBootstrapError):
                di._build_provider_from_spec(
                    config=config,
                    injector=injector,
                    spec=spec,
                    logger=logger,
                    strict_required=True,
                )

    def test_build_provider_from_spec_strict_required_raises_on_validate_injector_config(
        self,
    ) -> None:
        logger = Mock()

        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config):  # pylint: disable=unused-argument
                pass

        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:Dummy"}}}
        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            with self.assertRaises(di.ProviderBootstrapError):
                di._build_provider_from_spec(
                    config=config,
                    injector=object(),
                    spec=spec,
                    logger=logger,
                    validate_injector_config=True,
                    strict_required=True,
                )

    def test_build_provider_from_spec_strict_required_raises_on_attribute_error(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())

        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config, missing):  # pylint: disable=unused-argument
                pass

        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"), ("missing", "missing")),
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:Dummy"}}}
        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            with self.assertRaises(di.ProviderBootstrapError):
                di._build_provider_from_spec(
                    config=config,
                    injector=injector,
                    spec=spec,
                    logger=logger,
                    strict_required=True,
                )

    def test_build_provider_from_spec_strict_required_raises_on_constructor_exception(
        self,
    ) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())

        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config):  # pylint: disable=unused-argument
                raise ValueError("boom")

        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:Dummy"}}}
        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            with self.assertRaises(di.ProviderBootstrapError):
                di._build_provider_from_spec(
                    config=config,
                    injector=injector,
                    spec=spec,
                    logger=logger,
                    strict_required=True,
                )

    def test_build_provider_from_spec_constructor_exception_logs_error_for_required(self) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())

        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config):  # pylint: disable=unused-argument
                raise ValueError("boom")

        spec = di._ProviderSpec(
            provider_name="dummy_provider",
            injector_attr="dummy_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "dummy"),
            constructor_bindings=(("config", "config"),),
            required=True,
        )
        config = {"mugen": {"modules": {"dummy": "dummy.module:Dummy"}}}
        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            di._build_provider_from_spec(
                config=config,
                injector=injector,
                spec=spec,
                logger=logger,
                strict_required=False,
            )
        logger.error.assert_called_with("Invalid injector (dummy_provider).")

    def test_build_provider_from_spec_constructor_exception_logs_warning_for_optional(
        self,
    ) -> None:
        logger = Mock()
        injector = di.injector.DependencyInjector(config=object())

        class DummyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self, config):  # pylint: disable=unused-argument
                raise ValueError("boom")

        spec = di._ProviderSpec(
            provider_name="optional_provider",
            injector_attr="optional_provider",
            interface=ICompletionGateway,
            module_path=("mugen", "modules", "optional"),
            constructor_bindings=(("config", "config"),),
            required=False,
        )
        config = {"mugen": {"modules": {"optional": "dummy.module:Dummy"}}}
        with patch.object(di, "_resolve_provider_class", return_value=DummyProvider):
            di._build_provider_from_spec(
                config=config,
                injector=injector,
                spec=spec,
                logger=logger,
            )
        logger.warning.assert_called()
        self.assertIn(
            "Provider construction failed (optional_provider)",
            logger.warning.call_args.args[0],
        )

    def test_resolve_readiness_provider_names_keyval_only_by_default(self) -> None:
        config = self._readiness_config()
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            ["completion_gateway", "keyval_storage_gateway"],
        )

    def test_resolve_readiness_provider_names_includes_relational_when_configured(
        self,
    ) -> None:
        config = self._readiness_config(include_relational=True)
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            [
                "completion_gateway",
                "keyval_storage_gateway",
                "relational_storage_gateway",
            ],
        )

    def test_resolve_readiness_provider_names_web_profile_includes_web_store(self) -> None:
        config = self._readiness_config(
            profile="platform_full",
            platforms=[" web "],
            include_relational=False,
        )
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            [
                "completion_gateway",
                "keyval_storage_gateway",
                "relational_storage_gateway",
                "web_runtime_store",
            ],
        )

    def test_resolve_readiness_provider_names_includes_optional_io_gateways(self) -> None:
        config = self._readiness_config()
        config["mugen"]["modules"]["core"]["gateway"]["email"] = "email.mod:EmailProvider"  # type: ignore[index]
        config["mugen"]["modules"]["core"]["gateway"]["knowledge"] = (  # type: ignore[index]
            "knowledge.mod:KnowledgeProvider"
        )
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            [
                "completion_gateway",
                "keyval_storage_gateway",
                "email_gateway",
                "knowledge_gateway",
            ],
        )

    def test_resolve_readiness_provider_names_media_requires_web_platform(self) -> None:
        non_web_config = self._readiness_config(include_media=True)
        self.assertEqual(
            di._resolve_readiness_provider_names(non_web_config),
            ["completion_gateway", "keyval_storage_gateway"],
        )
        web_config = self._readiness_config(
            profile="platform_full",
            platforms=["web"],
            include_media=True,
        )
        self.assertEqual(
            di._resolve_readiness_provider_names(web_config),
            [
                "completion_gateway",
                "keyval_storage_gateway",
                "media_storage_gateway",
                "relational_storage_gateway",
                "web_runtime_store",
            ],
        )

    def test_await_readiness_probe_async_requires_awaitable(self) -> None:
        with self.assertRaises(di.ProviderBootstrapError) as raised:
            asyncio.run(
                di._await_readiness_probe_async(  # pylint: disable=protected-access
                    None,
                    provider_name="keyval_storage_gateway",
                    configured_token="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=1.0,
                )
            )
        self.assertIn("must return an awaitable", str(raised.exception))

    def test_await_readiness_probe_async_runs(self) -> None:
        marker = {"ready": False}

        async def _ready() -> None:
            marker["ready"] = True

        asyncio.run(
            di._await_readiness_probe_async(  # pylint: disable=protected-access
                _ready(),
                provider_name="keyval_storage_gateway",
                configured_token="mugen.gateway.keyval:KeyValProvider",
                timeout_seconds=1.0,
            )
        )
        self.assertTrue(marker["ready"])

    def test_await_readiness_probe_async_propagates_error(self) -> None:
        async def _boom() -> None:
            raise RuntimeError("readiness boom")

        with self.assertRaises(RuntimeError):
            asyncio.run(
                di._await_readiness_probe_async(  # pylint: disable=protected-access
                    _boom(),
                    provider_name="keyval_storage_gateway",
                    configured_token="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=1.0,
                )
            )

    def test_await_readiness_probe_async_times_out(self) -> None:
        async def _slow() -> None:
            await asyncio.sleep(0.2)

        with self.assertRaises(di.ProviderBootstrapError) as raised:
            asyncio.run(
                di._await_readiness_probe_async(  # pylint: disable=protected-access
                    _slow(),
                    provider_name="keyval_storage_gateway",
                    configured_token="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=0.01,
                )
            )
        self.assertIn("TimeoutError", str(raised.exception))

    def test_ensure_injector_readiness_async_succeeds_for_ready_provider(self) -> None:
        class _ReadyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self) -> None:
                self.ready = False

            async def check_readiness(self) -> None:
                self.ready = True

        provider = _ReadyProvider()
        completion_provider = _ReadyProvider()
        injector = di.injector.DependencyInjector(
            completion_gateway=completion_provider,
            keyval_storage_gateway=provider,
        )

        report = asyncio.run(
            di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )
        )
        self.assertTrue(provider.ready)
        self.assertTrue(completion_provider.ready)
        self.assertEqual(report.required_failures, {})
        self.assertEqual(report.optional_failures, {})

    def test_ensure_injector_readiness_async_fails_for_missing_provider(self) -> None:
        injector = di.injector.DependencyInjector()
        report = asyncio.run(
            di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )
        )
        self.assertIn("completion_gateway", report.required_failures)
        self.assertIn("token='deterministic'", report.required_failures["completion_gateway"])

    def test_ensure_injector_readiness_async_fails_for_missing_hook(self) -> None:
        class _ReadyProvider:  # pylint: disable=too-few-public-methods
            async def check_readiness(self) -> None:
                return None

        injector = di.injector.DependencyInjector(
            completion_gateway=_ReadyProvider(),
            keyval_storage_gateway=object(),
        )

        report = asyncio.run(
            di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )
        )
        self.assertIn("keyval_storage_gateway", report.required_failures)
        self.assertIn(
            "check_readiness is unavailable",
            report.required_failures["keyval_storage_gateway"],
        )

    def test_ensure_injector_readiness_async_wraps_provider_exception(self) -> None:
        class _ReadyProvider:  # pylint: disable=too-few-public-methods
            async def check_readiness(self) -> None:
                return None

        class _FailingProvider:  # pylint: disable=too-few-public-methods
            async def check_readiness(self) -> None:
                raise RuntimeError("backend unavailable")

        injector = di.injector.DependencyInjector(
            completion_gateway=_ReadyProvider(),
            keyval_storage_gateway=_FailingProvider(),
        )

        report = asyncio.run(
            di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )
        )
        self.assertIn("keyval_storage_gateway", report.required_failures)
        self.assertIn(
            "RuntimeError: backend unavailable",
            report.required_failures["keyval_storage_gateway"],
        )

    def test_ensure_injector_readiness_async_preserves_bootstrap_error(self) -> None:
        class _Provider:  # pylint: disable=too-few-public-methods
            def check_readiness(self) -> None:
                return None

        injector = di.injector.DependencyInjector(
            completion_gateway=_Provider(),
            keyval_storage_gateway=_Provider(),
        )

        with patch(
            "mugen.core.di._await_readiness_probe_async",
            side_effect=di.ProviderBootstrapError("forced bootstrap error"),
        ):
            report = asyncio.run(
                di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                    self._readiness_config(),
                    injector,
                )
            )
        failures_text = " ".join(report.required_failures.values())
        self.assertIn("forced bootstrap error", failures_text)

    def test_ensure_injector_readiness_async_collects_optional_failures(self) -> None:
        class _ReadyProvider:  # pylint: disable=too-few-public-methods
            async def check_readiness(self) -> None:
                return None

        injector = di.injector.DependencyInjector(
            completion_gateway=_ReadyProvider(),
            keyval_storage_gateway=_ReadyProvider(),
            email_gateway=object(),
        )
        config = self._readiness_config()
        config["mugen"]["modules"]["core"]["gateway"]["email"] = "smtp"

        report = asyncio.run(
            di._ensure_injector_readiness_async(  # pylint: disable=protected-access
                config,
                injector,
            )
        )
        self.assertIn("email_gateway", report.optional_failures)
        self.assertEqual(report.required_failures, {})

    def test_format_required_readiness_failure_message_handles_empty_and_populated(self) -> None:
        empty_report = di.ProviderReadinessReport(
            successful_providers=(),
            required_failures={},
            optional_failures={},
        )
        self.assertEqual(
            di._format_required_readiness_failure_message(empty_report),  # pylint: disable=protected-access
            "Provider readiness failed.",
        )

        report = di.ProviderReadinessReport(
            successful_providers=(),
            required_failures={"b": "failure-b", "a": "failure-a"},
            optional_failures={},
        )
        self.assertEqual(
            di._format_required_readiness_failure_message(report),  # pylint: disable=protected-access
            "failure-a; failure-b",
        )

    def test_resolve_provider_readiness_timeout_seconds_defaults_and_validation(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_provider_readiness_timeout_seconds({})  # pylint: disable=protected-access
        self.assertEqual(
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_readiness_timeout_seconds="2.5",
                        )
                    }
                }
            ),
            2.5,
        )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_readiness_timeout_seconds="bad",
                        )
                    }
                }
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_readiness_timeout_seconds=0,
                        )
                    }
                }
            )

    def test_resolve_provider_shutdown_timeout_seconds_required_and_validation(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_provider_shutdown_timeout_seconds({})  # pylint: disable=protected-access
        self.assertEqual(
            di._resolve_provider_shutdown_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_shutdown_timeout_seconds="2.5",
                        )
                    }
                }
            ),
            2.5,
        )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_shutdown_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_shutdown_timeout_seconds="bad",
                        )
                    }
                }
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_shutdown_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            provider_shutdown_timeout_seconds=0,
                        )
                    }
                }
            )

    def test_resolve_shutdown_timeout_seconds_required_and_validation(self) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_shutdown_timeout_seconds({})  # pylint: disable=protected-access
        self.assertEqual(
            di._resolve_shutdown_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            shutdown_timeout_seconds="5.0",
                        )
                    }
                }
            ),
            5.0,
        )
        with self.assertRaises(RuntimeError):
            di._resolve_shutdown_timeout_seconds(  # pylint: disable=protected-access
                {
                    "mugen": {
                        "runtime": self._runtime_section(
                            shutdown_timeout_seconds=0,
                        )
                    }
                }
            )

    def test_build_shared_relational_runtime_requires_valid_injector_and_config(self) -> None:
        with self.assertRaises(RuntimeError):
            di._build_shared_relational_runtime(None)  # type: ignore[arg-type]  # pylint: disable=protected-access

        injector = di.injector.DependencyInjector(config=None)
        with self.assertRaises(RuntimeError):
            di._build_shared_relational_runtime(injector)  # pylint: disable=protected-access

    def test_injector_config_dict_validation_branches(self) -> None:
        with self.assertRaises(RuntimeError):
            di._injector_config_dict(None)  # pylint: disable=protected-access

        injector = di.injector.DependencyInjector(config=SimpleNamespace())
        with self.assertRaises(RuntimeError):
            di._injector_config_dict(injector)  # pylint: disable=protected-access

    def test_injector_config_dict_returns_dict_when_available(self) -> None:
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(dict={"mugen": {"runtime": {"profile": "platform_full"}}})
        )
        resolved = di._injector_config_dict(injector)  # pylint: disable=protected-access
        self.assertEqual(resolved["mugen"]["runtime"]["profile"], "platform_full")

    def test_container_proxy_ensure_readiness_short_circuits_when_cached(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(dict={"mugen": {"runtime": {"profile": "platform_full"}}})
        )
        proxy._injector = injector  # pylint: disable=protected-access
        proxy._readiness_checked = True  # pylint: disable=protected-access

        resolved = asyncio.run(proxy.ensure_readiness())
        self.assertIs(resolved, injector)

    def test_container_proxy_ensure_readiness_runs_readiness_and_validation(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(dict={"mugen": {"runtime": {"profile": "platform_full"}}})
        )
        proxy._injector = injector  # pylint: disable=protected-access
        proxy._readiness_checked = False  # pylint: disable=protected-access

        readiness_mock = unittest.mock.AsyncMock(
            return_value=di.ProviderReadinessReport(
                successful_providers=("completion_gateway",),
                required_failures={},
                optional_failures={},
            )
        )
        validate_mock = unittest.mock.Mock()
        with patch(
            "mugen.core.di._ensure_injector_readiness_async",
            new=readiness_mock,
        ), patch(
            "mugen.core.di._validate_container",
            new=validate_mock,
        ):
            resolved = asyncio.run(proxy.ensure_readiness())

        self.assertIs(resolved, injector)
        readiness_mock.assert_awaited_once()
        validate_mock.assert_called_once()
        self.assertTrue(proxy._readiness_checked)  # pylint: disable=protected-access

    def test_container_proxy_ensure_readiness_raises_for_required_failures(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(dict={"mugen": {"runtime": {"profile": "platform_full"}}})
        )
        proxy._injector = injector  # pylint: disable=protected-access

        readiness_mock = unittest.mock.AsyncMock(
            return_value=di.ProviderReadinessReport(
                successful_providers=(),
                required_failures={"completion_gateway": "completion down"},
                optional_failures={},
            )
        )

        with patch(
            "mugen.core.di._ensure_injector_readiness_async",
            new=readiness_mock,
        ), patch(
            "mugen.core.di._validate_container",
            new=unittest.mock.Mock(),
        ):
            with self.assertRaises(di.ProviderBootstrapError):
                asyncio.run(proxy.ensure_readiness())

    def test_container_proxy_ensure_readiness_wraps_runtime_config_errors(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        proxy._injector = di.injector.DependencyInjector(  # pylint: disable=protected-access
            config=SimpleNamespace(dict={"mugen": {"runtime": {"profile": "platform_full"}}})
        )

        with patch(
            "mugen.core.di._injector_config_dict",
            side_effect=RuntimeError("missing runtime controls"),
        ):
            with self.assertRaises(di.ProviderBootstrapError) as raised:
                asyncio.run(proxy.ensure_readiness())

        self.assertIn(
            "Provider readiness bootstrap configuration failed: missing runtime controls",
            str(raised.exception),
        )

    def test_container_proxy_get_readiness_report_returns_last_report(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        report = di.ProviderReadinessReport(
            successful_providers=("completion_gateway",),
            required_failures={},
            optional_failures={},
        )
        proxy._last_readiness_report = report  # pylint: disable=protected-access
        self.assertIs(proxy.get_readiness_report(), report)

    def test_ensure_container_readiness_async_delegates_to_proxy(self) -> None:
        sentinel_injector = object()
        ensure_mock = unittest.mock.AsyncMock(return_value=sentinel_injector)
        fake_container = SimpleNamespace(ensure_readiness=ensure_mock)
        with patch("mugen.core.di.container", fake_container):
            resolved = asyncio.run(di.ensure_container_readiness_async())

        self.assertIs(resolved, sentinel_injector)
        ensure_mock.assert_awaited_once_with()
