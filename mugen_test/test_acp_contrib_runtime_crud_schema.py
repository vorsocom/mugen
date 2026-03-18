"""Focused tests for ACP runtime CRUD schema registration and validation."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(
            config=SimpleNamespace(),
            logging_gateway=SimpleNamespace(debug=lambda *_: None),
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

from mugen.core.plugin.acp.api.validation.runtime import (  # noqa: E402
    # pylint: disable=wrong-import-position
    MessagingClientProfileCreateValidation,
    MessagingClientProfileUpdateValidation,
    RuntimeConfigProfileCreateValidation,
    RuntimeConfigProfileUpdateValidation,
)
from mugen.core.plugin.acp.contrib import contribute  # noqa: E402
from mugen.core.plugin.acp.sdk.registry import AdminRegistry  # noqa: E402


class TestAcpContribRuntimeCrudSchema(unittest.TestCase):
    """Tests ACP runtime CRUD schema registration and validation semantics."""

    def test_runtime_resources_have_explicit_crud_schema(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        runtime_profiles = registry.get_resource("RuntimeConfigProfiles")
        self.assertEqual(
            runtime_profiles.crud.create_schema,
            RuntimeConfigProfileCreateValidation,
        )
        self.assertEqual(
            runtime_profiles.crud.update_schema,
            RuntimeConfigProfileUpdateValidation,
        )

        client_profiles = registry.get_resource("MessagingClientProfiles")
        self.assertEqual(
            client_profiles.crud.create_schema,
            MessagingClientProfileCreateValidation,
        )
        self.assertEqual(
            client_profiles.crud.update_schema,
            MessagingClientProfileUpdateValidation,
        )

    def test_runtime_config_profile_validation_keeps_optional_fields_optional(
        self,
    ) -> None:
        create_validation = RuntimeConfigProfileCreateValidation(
            category=" messaging.platform_defaults ",
            profile_key=" whatsapp ",
        )
        self.assertEqual(
            create_validation.category,
            "messaging.platform_defaults",
        )
        self.assertEqual(create_validation.profile_key, "whatsapp")
        self.assertIsNone(create_validation.display_name)
        self.assertEqual(create_validation.settings_json, {})

        update_validation = RuntimeConfigProfileUpdateValidation(
            display_name=" Tenant WhatsApp defaults ",
        )
        self.assertEqual(update_validation.display_name, "Tenant WhatsApp defaults")

        with self.assertRaisesRegex(ValueError, "At least one mutable field"):
            RuntimeConfigProfileUpdateValidation()

    def test_runtime_config_profile_validation_normalizes_updates_and_surfaces_policy_errors(
        self,
    ) -> None:
        validation = RuntimeConfigProfileCreateValidation(
            category=" messaging.platform_defaults ",
            profile_key=" whatsapp ",
            display_name=" Tenant WhatsApp defaults ",
        )
        self.assertEqual(validation.display_name, "Tenant WhatsApp defaults")

        update_validation = RuntimeConfigProfileUpdateValidation(
            category=" messaging.platform_defaults ",
            profile_key=" whatsapp ",
            display_name=" Updated defaults ",
            settings_json={"app": {"id": "4262120864004605"}},
            attributes={"priority": "gold"},
        )
        self.assertEqual(
            update_validation.category,
            "messaging.platform_defaults",
        )
        self.assertEqual(update_validation.profile_key, "whatsapp")
        self.assertEqual(update_validation.display_name, "Updated defaults")
        self.assertEqual(
            update_validation.settings_json,
            {"app": {"id": "4262120864004605"}},
        )
        self.assertEqual(update_validation.attributes, {"priority": "gold"})

        with self.assertRaisesRegex(
            ValueError,
            "ProfileKey must be non-empty when provided.",
        ):
            RuntimeConfigProfileUpdateValidation(profile_key=" ")

        with self.assertRaises(ValueError):
            RuntimeConfigProfileCreateValidation(
                category="messaging.platform_defaults",
                profile_key="whatsapp",
                settings_json={"invalid": {"path": "value"}},
            )

        with self.assertRaises(ValueError):
            RuntimeConfigProfileUpdateValidation(
                category="messaging.platform_defaults",
                profile_key="whatsapp",
                settings_json={"invalid": {"path": "value"}},
            )

    def test_messaging_client_profile_create_uses_platform_specific_requiredness(
        self,
    ) -> None:
        validation = MessagingClientProfileCreateValidation(
            platform_key=" whatsapp ",
            profile_key=" global-default ",
            path_token=" token ",
            phone_number_id=" 1022458200954640 ",
        )

        self.assertEqual(validation.platform_key, "whatsapp")
        self.assertEqual(validation.profile_key, "global-default")
        self.assertEqual(validation.path_token, "token")
        self.assertEqual(validation.phone_number_id, "1022458200954640")
        self.assertIsNone(validation.provider)

        with self.assertRaisesRegex(ValueError, "phone_number_id is required"):
            MessagingClientProfileCreateValidation(
                platform_key="whatsapp",
                profile_key="global-default",
                path_token="token",
            )

        with self.assertRaisesRegex(ValueError, "At least one mutable field"):
            MessagingClientProfileUpdateValidation()

    def test_messaging_client_profile_update_normalizes_fields_and_wraps_policy_errors(
        self,
    ) -> None:
        validation = MessagingClientProfileUpdateValidation(
            platform_key=" whatsapp ",
            profile_key=" global-default ",
            display_name=" WhatsApp global default ",
            settings={"app": {"id": "4262120864004605"}},
            secret_refs={
                "graphapi.access_token": "11111111-1111-1111-1111-111111111111",
                "app.secret": "22222222-2222-2222-2222-222222222222",
            },
            path_token=" token ",
            phone_number_id=" 1022458200954640 ",
            provider=None,
        )
        self.assertEqual(validation.platform_key, "whatsapp")
        self.assertEqual(validation.profile_key, "global-default")
        self.assertEqual(validation.display_name, "WhatsApp global default")
        self.assertEqual(validation.settings, {"app": {"id": "4262120864004605"}})
        self.assertEqual(
            validation.secret_refs,
            {
                "graphapi.access_token": "11111111-1111-1111-1111-111111111111",
                "app.secret": "22222222-2222-2222-2222-222222222222",
            },
        )
        self.assertEqual(validation.path_token, "token")
        self.assertEqual(validation.phone_number_id, "1022458200954640")
        self.assertIsNone(validation.provider)

        minimal_validation = MessagingClientProfileUpdateValidation(
            profile_key=" alternate-default ",
        )
        self.assertEqual(minimal_validation.profile_key, "alternate-default")

        with self.assertRaises(ValueError):
            MessagingClientProfileCreateValidation(
                platform_key="unsupported",
                profile_key="global-default",
            )

        with self.assertRaises(ValueError):
            MessagingClientProfileUpdateValidation(
                platform_key="whatsapp",
                secret_refs={
                    "invalid.path": "11111111-1111-1111-1111-111111111111"
                },
            )


if __name__ == "__main__":
    unittest.main()
