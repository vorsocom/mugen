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
                "modules": {"core": {"gateway": {"knowledge": "knowledge.module"}}},
                "platforms": ["matrix", "telnet", "whatsapp", "web"],
            }
        }

        with self.assertRaises(RuntimeError):
            di._validate_container(config, injector)

        injector.logging_gateway.error.assert_any_call("Missing provider (knowledge_gateway).")
        injector.logging_gateway.error.assert_any_call("Missing provider (matrix_client).")
        injector.logging_gateway.error.assert_any_call("Missing provider (telnet_client).")
        injector.logging_gateway.error.assert_any_call("Missing provider (whatsapp_client).")
        injector.logging_gateway.error.assert_any_call("Missing provider (web_client).")

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
        config = {"mugen": {"platforms": ["matrix"]}}

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
                "platforms": [],
            }
        }

        di._validate_container(config, injector)

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

    def test_container_proxy_setattr_forwards_non_internal_attrs(self) -> None:
        proxy = di._ContainerProxy()
        target = SimpleNamespace()
        proxy._injector = target
        proxy.some_attribute = "value"
        self.assertEqual(target.some_attribute, "value")
