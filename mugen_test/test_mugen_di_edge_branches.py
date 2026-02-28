"""Edge-branch unit tests for mugen.core.di helper routines."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


# pylint: disable=protected-access
class TestMugenDIEdgeBranches(unittest.TestCase):
    """Exercise remaining branch-heavy DI helpers."""

    def test_get_provider_class_logs_when_multiple_matches_exist(self) -> None:
        class FirstCompletionGateway(ICompletionGateway):
            async def get_completion(self, context, operation="completion"):
                return None

        class SecondCompletionGateway(ICompletionGateway):
            async def get_completion(self, context, operation="completion"):
                return None

        FirstCompletionGateway.__module__ = "module.same"
        SecondCompletionGateway.__module__ = "module.same"

        logger = Mock()
        with patch(
            "mugen.core.contract.gateway.completion.ICompletionGateway.__subclasses__",
            return_value=[FirstCompletionGateway, SecondCompletionGateway],
        ):
            provider = di._get_provider_class(
                interface=ICompletionGateway,
                module_name="module.same",
                provider_name="completion_gateway",
                logger=logger,
            )

        self.assertIsNone(provider)
        logger.error.assert_called_once_with(
            "Multiple valid subclasses found (completion_gateway)."
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

        with (
            patch.object(di, "_import_provider_module", return_value="dummy.module"),
            patch.object(di, "_get_provider_class", return_value=DummyProvider),
        ):
            di._build_provider_from_spec(
                {},
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

        with patch.object(di, "_import_provider_module", return_value=None) as import_module:
            di._build_provider_from_spec(
                {"mugen": {"platforms": [" WEB "]}},
                injector,
                spec=spec,
                logger=logger,
            )

        import_module.assert_called_once()
        logger.warning.assert_not_called()

    def test_container_proxy_setattr_forwards_non_internal_attrs(self) -> None:
        proxy = di._ContainerProxy()
        target = SimpleNamespace()
        proxy._injector = target
        proxy.some_attribute = "value"
        self.assertEqual(target.some_attribute, "value")
