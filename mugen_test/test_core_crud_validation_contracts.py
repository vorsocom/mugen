"""Guardrails for explicit CRUD validation contracts on core ACP resources."""

import unittest

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.api.validation.generic import NoValidationSchema
from mugen.core.plugin.acp.contrib import contribute as contribute_acp
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.billing.contrib import contribute as contribute_billing
from mugen.core.plugin.channel_orchestration.contrib import (
    contribute as contribute_channel_orchestration,
)
from mugen.core.plugin.context_engine.contrib import (
    contribute as contribute_context_engine,
)
from mugen.core.plugin.knowledge_pack.contrib import (
    contribute as contribute_knowledge_pack,
)
from mugen.core.plugin.ops_case.contrib import contribute as contribute_ops_case
from mugen.core.plugin.ops_connector.contrib import (
    contribute as contribute_ops_connector,
)
from mugen.core.plugin.ops_governance.contrib import (
    contribute as contribute_ops_governance,
)
from mugen.core.plugin.ops_metering.contrib import (
    contribute as contribute_ops_metering,
)
from mugen.core.plugin.ops_reporting.contrib import (
    contribute as contribute_ops_reporting,
)
from mugen.core.plugin.ops_sla.contrib import contribute as contribute_ops_sla
from mugen.core.plugin.ops_vpn.contrib import contribute as contribute_ops_vpn
from mugen.core.plugin.ops_workflow.contrib import (
    contribute as contribute_ops_workflow,
)


class TestCoreCrudValidationContracts(unittest.TestCase):
    """Ensures core create/update resources use explicit Pydantic schemas."""

    def _build_registry(self) -> AdminRegistry:
        admin_ns = AdminNs("com.test.admin")
        registry = AdminRegistry(strict_permission_decls=True)
        contribute_acp(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace=admin_ns.ns,
        )

        contributors = (
            (contribute_billing, "com.test.billing"),
            (
                contribute_channel_orchestration,
                "com.test.channel_orchestration",
            ),
            (contribute_context_engine, "com.test.context_engine"),
            (contribute_knowledge_pack, "com.test.knowledge_pack"),
            (contribute_ops_case, "com.test.ops_case"),
            (contribute_ops_connector, "com.test.ops_connector"),
            (contribute_ops_governance, "com.test.ops_governance"),
            (contribute_ops_metering, "com.test.ops_metering"),
            (contribute_ops_reporting, "com.test.ops_reporting"),
            (contribute_ops_sla, "com.test.ops_sla"),
            (contribute_ops_vpn, "com.test.ops_vpn"),
            (contribute_ops_workflow, "com.test.ops_workflow"),
        )

        for contribute_fn, plugin_namespace in contributors:
            contribute_fn(
                registry,
                admin_namespace=admin_ns.ns,
                plugin_namespace=plugin_namespace,
            )

        return registry

    def test_enabled_create_update_resources_use_explicit_validation_models(
        self,
    ) -> None:
        registry = self._build_registry()
        violations: list[str] = []

        for resource in registry.resources.values():
            if resource.capabilities.allow_create:
                schema = resource.crud.create_schema
                if (
                    not isinstance(schema, type)
                    or not issubclass(schema, IValidationBase)
                    or schema is NoValidationSchema
                ):
                    violations.append(
                        f"{resource.entity_set}.create={schema!r}"
                    )

            if resource.capabilities.allow_update:
                schema = resource.crud.update_schema
                if (
                    not isinstance(schema, type)
                    or not issubclass(schema, IValidationBase)
                    or schema is NoValidationSchema
                ):
                    violations.append(
                        f"{resource.entity_set}.update={schema!r}"
                    )

        self.assertEqual(violations, [])

    def test_generated_crud_validation_normalizes_text_and_rejects_empty_updates(
        self,
    ) -> None:
        create_schema = build_create_validation_from_pascal(
            "GeneratedCrudCreateValidation",
            module=__name__,
            doc="Validate generated create payloads.",
            required_fields=("Name",),
            optional_fields=("DisplayName",),
        )
        create_validation = create_schema(
            name=" Example ",
            display_name=" Visible name ",
        )
        self.assertEqual(create_validation.name, "Example")
        self.assertEqual(create_validation.display_name, "Visible name")

        with self.assertRaisesRegex(ValueError, "Name must be non-empty."):
            create_schema(name=" ")

        with self.assertRaisesRegex(
            ValueError,
            "DisplayName must be non-empty when provided.",
        ):
            create_schema(name="Example", display_name=" ")

        update_schema = build_update_validation_from_pascal(
            "GeneratedCrudUpdateValidation",
            module=__name__,
            doc="Validate generated update payloads.",
            optional_fields=("DisplayName", "IsActive"),
        )
        update_validation = update_schema(display_name=" Updated ", is_active=False)
        self.assertEqual(update_validation.display_name, "Updated")
        self.assertFalse(update_validation.is_active)

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable field must be provided.",
        ):
            update_schema()

        with self.assertRaisesRegex(
            ValueError,
            "DisplayName must be non-empty when provided.",
        ):
            update_schema(display_name=" ")


if __name__ == "__main__":
    unittest.main()
