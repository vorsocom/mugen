"""Edge-branch unit tests for mugen.core.di helper routines."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


class _CloseAwareAwaitable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def __await__(self):
        if False:
            yield
        return None


# pylint: disable=protected-access
class TestMugenDIEdgeBranches(unittest.TestCase):
    """Exercise remaining branch-heavy DI helpers."""

    @staticmethod
    def _readiness_config(
        *,
        profile: str = "api_only",
        platforms: list[str] | None = None,
        include_relational: bool = False,
    ) -> dict:
        config: dict = {
            "mugen": {
                "runtime": {"profile": profile},
                "platforms": [] if platforms is None else platforms,
                "modules": {
                    "core": {
                        "gateway": {
                            "storage": {
                                "keyval": "mugen.gateway.keyval:KeyValProvider",
                            }
                        }
                    }
                },
            }
        }
        if include_relational:
            config["mugen"]["modules"]["core"]["gateway"]["storage"]["relational"] = (  # type: ignore[index]
                "mugen.gateway.rdbms:RelationalProvider"
            )
        return config

    def test_split_class_path_rejects_module_only_value(self) -> None:
        with self.assertRaises(RuntimeError):
            di._split_class_path(
                "module.only",
                provider_name="completion_gateway",
            )

    def test_config_path_exists_handles_non_dict_missing_and_present_paths(self) -> None:
        self.assertFalse(di._config_path_exists({"mugen": []}, "mugen", "modules"))
        self.assertFalse(di._config_path_exists({"mugen": {}}, "mugen", "modules"))
        self.assertTrue(di._config_path_exists({"mugen": {"modules": {}}}, "mugen", "modules"))

    def test_get_active_platforms_requires_list(self) -> None:
        self.assertIsNone(di._get_active_platforms({"mugen": {"platforms": "matrix"}}))
        self.assertEqual(di._get_active_platforms({"mugen": {"platforms": ["matrix"]}}), ["matrix"])

    def test_infer_runtime_profile(self) -> None:
        self.assertEqual(
            di._infer_runtime_profile({"mugen": {"runtime": {"profile": "api_only"}}}),
            "api_only",
        )
        self.assertEqual(
            di._infer_runtime_profile(
                {"mugen": {"runtime": {"profile": "platform_full"}, "platforms": ["matrix", "web"]}}
            ),
            "platform_full",
        )
        self.assertEqual(
            di._infer_runtime_profile(
                {"mugen": {"runtime": {"profile": "api_only"}, "platforms": ["web"]}}
            ),
            "api_only",
        )
        self.assertEqual(
            di._infer_runtime_profile(
                {"mugen": {"runtime": {"profile": "platform_full"}, "platforms": []}}
            ),
            "platform_full",
        )

    def test_infer_runtime_profile_rejects_invalid_override(self) -> None:
        with self.assertRaises(RuntimeError):
            di._infer_runtime_profile({"mugen": {"runtime": {"profile": "invalid"}}})
        with self.assertRaises(RuntimeError):
            di._infer_runtime_profile({"mugen": {"platforms": []}})

    def test_normalize_platforms_filters_empty_and_duplicates(self) -> None:
        self.assertEqual(di._normalize_platforms(None), [])
        self.assertEqual(
            di._normalize_platforms([" web ", "", "web", "matrix"]),
            ["web", "matrix"],
        )

    def test_runtime_profile_override_edge_cases(self) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"profile": None}}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"profile": "   "}}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"profile": "auto"}}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"profile": 1}}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {"runtime": {}}}
            )
        with self.assertRaises(RuntimeError):
            di._resolve_runtime_profile_override(  # pylint: disable=protected-access
                {"mugen": {}}
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
                "runtime": {"profile": "web_only"},
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
                "runtime": {"profile": "platform_full"},
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

    def test_validate_container_rejects_removed_legacy_keyval_paths(self) -> None:
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=Mock(),
            completion_gateway=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            nlp_service=object(),
            platform_service=object(),
            user_service=object(),
            messaging_service=object(),
        )

        with self.assertRaises(RuntimeError):
            di._validate_container(
                {
                    "mugen": {
                        "runtime": {"profile": "api_only"},
                        "platforms": [],
                        "storage": {"keyval": {"legacy_import": {"enabled": False}}},
                    }
                },
                injector,
            )

        with self.assertRaises(RuntimeError):
            di._validate_container(
                {
                    "mugen": {
                        "runtime": {"profile": "api_only"},
                        "platforms": [],
                        "modules": {
                            "core": {
                                "client": {
                                    "telnet": "mugen.core.client.telnet"
                                }
                            }
                        },
                    }
                },
                injector,
            )

        with self.assertRaises(RuntimeError):
            di._validate_container(
                {
                    "mugen": {
                        "runtime": {"profile": "api_only"},
                        "platforms": [],
                        "modules": {
                            "core": {
                                "gateway": {
                                    "storage": {
                                        "keyval": "mugen.core.gateway.storage.keyval.dbm"
                                    }
                                }
                            }
                        },
                    }
                },
                injector,
            )

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
        config = {"mugen": {"runtime": {"profile": "platform_full"}, "platforms": ["matrix"]}}

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
        )
        config = {
            "mugen": {
                "modules": {"core": {"gateway": {"knowledge": "knowledge.module"}}},
                "runtime": {"profile": "api_only"},
                "platforms": [],
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
        )
        config = {
            "mugen": {
                "modules": {"core": {"gateway": {"email": "email.module"}}},
                "runtime": {"profile": "api_only"},
                "platforms": [],
            }
        }

        di._validate_container(config, injector)

    def test_validate_container_rejects_api_only_with_enabled_platforms(self) -> None:
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
                "runtime": {"profile": "api_only"},
                "platforms": ["web"],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

    def test_validate_container_rejects_web_only_profile_without_web_platform(self) -> None:
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
                "runtime": {"profile": "web_only"},
                "platforms": ["matrix"],
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
                "runtime": {"profile": "platform_full"},
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
                "runtime": {"profile": "platform_full"},
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
                "runtime": {"profile": "platform_full"},
                "platforms": [" web ", "unknown"],
            }
        }
        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

        self.assertTrue(
            any(
                call.args[0] == "Unsupported platform configuration detected: %s."
                and call.args[1] == "unknown"
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
            ["keyval_storage_gateway"],
        )

    def test_resolve_readiness_provider_names_includes_relational_when_configured(
        self,
    ) -> None:
        config = self._readiness_config(include_relational=True)
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            ["keyval_storage_gateway", "relational_storage_gateway"],
        )

    def test_resolve_readiness_provider_names_web_profile_includes_web_store(self) -> None:
        config = self._readiness_config(
            profile="web_only",
            platforms=[" web "],
            include_relational=False,
        )
        self.assertEqual(
            di._resolve_readiness_provider_names(config),
            [
                "keyval_storage_gateway",
                "relational_storage_gateway",
                "web_runtime_store",
            ],
        )

    def test_await_readiness_probe_sync_returns_for_non_awaitable(self) -> None:
        di._await_readiness_probe_sync(  # pylint: disable=protected-access
            None,
            provider_name="keyval_storage_gateway",
            configured_class_path="mugen.gateway.keyval:KeyValProvider",
            timeout_seconds=1.0,
        )

    def test_await_readiness_probe_sync_runs_when_no_event_loop(self) -> None:
        awaitable = _CloseAwareAwaitable()
        with patch(
            "mugen.core.di.asyncio.get_running_loop",
            side_effect=RuntimeError,
        ):
            with patch("mugen.core.di.asyncio.run") as run_mock:
                di._await_readiness_probe_sync(  # pylint: disable=protected-access
                    awaitable,
                    provider_name="keyval_storage_gateway",
                    configured_class_path="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=1.0,
                )
        run_mock.assert_called_once()
        run_arg = run_mock.call_args.args[0]
        close = getattr(run_arg, "close", None)
        if callable(close):
            close()

    def test_await_readiness_probe_sync_runs_in_thread_when_loop_is_running(
        self,
    ) -> None:
        marker = {"ready": False}

        async def _ready() -> None:
            marker["ready"] = True

        with patch(
            "mugen.core.di.asyncio.get_running_loop",
            return_value=object(),
        ):
            di._await_readiness_probe_sync(  # pylint: disable=protected-access
                _ready(),
                provider_name="keyval_storage_gateway",
                configured_class_path="mugen.gateway.keyval:KeyValProvider",
                timeout_seconds=1.0,
            )
        self.assertTrue(marker["ready"])

    def test_await_readiness_probe_sync_propagates_thread_error(self) -> None:
        async def _boom() -> None:
            raise RuntimeError("readiness boom")

        with patch(
            "mugen.core.di.asyncio.get_running_loop",
            return_value=object(),
        ):
            with self.assertRaises(di.ProviderBootstrapError) as raised:
                di._await_readiness_probe_sync(  # pylint: disable=protected-access
                    _boom(),
                    provider_name="keyval_storage_gateway",
                    configured_class_path="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=1.0,
                )
        self.assertIn("RuntimeError: readiness boom", str(raised.exception))

    def test_await_readiness_probe_sync_times_out_thread_worker(self) -> None:
        async def _slow() -> None:
            await asyncio.sleep(0.2)

        with patch(
            "mugen.core.di.asyncio.get_running_loop",
            return_value=object(),
        ):
            with self.assertRaises(di.ProviderBootstrapError) as raised:
                di._await_readiness_probe_sync(  # pylint: disable=protected-access
                    _slow(),
                    provider_name="keyval_storage_gateway",
                    configured_class_path="mugen.gateway.keyval:KeyValProvider",
                    timeout_seconds=0.01,
                )
        self.assertIn("TimeoutError", str(raised.exception))

    def test_await_readiness_probe_sync_raises_when_worker_result_is_missing(self) -> None:
        async def _ready() -> None:
            return None

        with patch(
            "mugen.core.di.asyncio.get_running_loop",
            return_value=object(),
        ):
            with patch(
                "mugen.core.di.Queue.get_nowait",
                side_effect=RuntimeError("queue-read-failed"),
            ):
                with self.assertRaises(di.ProviderBootstrapError) as raised:
                    di._await_readiness_probe_sync(  # pylint: disable=protected-access
                        _ready(),
                        provider_name="keyval_storage_gateway",
                        configured_class_path="mugen.gateway.keyval:KeyValProvider",
                        timeout_seconds=1.0,
                    )
        self.assertIn("did not report result", str(raised.exception))

    def test_validate_required_provider_readiness_succeeds_for_ready_provider(self) -> None:
        class _ReadyProvider:  # pylint: disable=too-few-public-methods
            def __init__(self) -> None:
                self.ready = False

            async def check_readiness(self) -> None:
                self.ready = True

        provider = _ReadyProvider()
        injector = di.injector.DependencyInjector(
            keyval_storage_gateway=provider,
        )

        di._validate_required_provider_readiness(  # pylint: disable=protected-access
            self._readiness_config(),
            injector,
        )
        self.assertTrue(provider.ready)

    def test_validate_required_provider_readiness_fails_for_missing_provider(self) -> None:
        injector = di.injector.DependencyInjector()
        with self.assertRaises(di.ProviderBootstrapError) as raised:
            di._validate_required_provider_readiness(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )

        self.assertIn("keyval_storage_gateway", str(raised.exception))
        self.assertIn("mugen.gateway.keyval:KeyValProvider", str(raised.exception))

    def test_validate_required_provider_readiness_fails_for_missing_hook(self) -> None:
        injector = di.injector.DependencyInjector(
            keyval_storage_gateway=object(),
        )

        with self.assertRaises(di.ProviderBootstrapError) as raised:
            di._validate_required_provider_readiness(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )

        self.assertIn("check_readiness is unavailable", str(raised.exception))

    def test_validate_required_provider_readiness_wraps_provider_exception(self) -> None:
        class _FailingProvider:  # pylint: disable=too-few-public-methods
            async def check_readiness(self) -> None:
                raise RuntimeError("backend unavailable")

        injector = di.injector.DependencyInjector(
            keyval_storage_gateway=_FailingProvider(),
        )

        with self.assertRaises(di.ProviderBootstrapError) as raised:
            di._validate_required_provider_readiness(  # pylint: disable=protected-access
                self._readiness_config(),
                injector,
            )

        self.assertIn("RuntimeError: backend unavailable", str(raised.exception))

    def test_validate_required_provider_readiness_preserves_bootstrap_error(self) -> None:
        class _Provider:  # pylint: disable=too-few-public-methods
            def check_readiness(self) -> None:
                return None

        injector = di.injector.DependencyInjector(
            keyval_storage_gateway=_Provider(),
        )

        with patch(
            "mugen.core.di._await_readiness_probe_sync",
            side_effect=di.ProviderBootstrapError("forced bootstrap error"),
        ):
            with self.assertRaises(di.ProviderBootstrapError) as raised:
                di._validate_required_provider_readiness(  # pylint: disable=protected-access
                    self._readiness_config(),
                    injector,
                )
        self.assertEqual(str(raised.exception), "forced bootstrap error")

    def test_resolve_provider_readiness_timeout_seconds_defaults_and_validation(
        self,
    ) -> None:
        self.assertEqual(
            di._resolve_provider_readiness_timeout_seconds({}),  # pylint: disable=protected-access
            15.0,
        )
        self.assertEqual(
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"provider_readiness_timeout_seconds": "2.5"}}}
            ),
            2.5,
        )
        self.assertEqual(
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"provider_readiness_timeout_seconds": "bad"}}}
            ),
            15.0,
        )
        self.assertEqual(
            di._resolve_provider_readiness_timeout_seconds(  # pylint: disable=protected-access
                {"mugen": {"runtime": {"provider_readiness_timeout_seconds": 0}}}
            ),
            15.0,
        )
