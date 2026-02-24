"""Guard that ACP action declarations map to callable service handlers."""

from __future__ import annotations

import importlib
import unittest

from mugen.core.plugin.acp.contrib import contribute
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def register_tables(self, _tables) -> None:
        return


def _load_provider_attr(provider: str):
    mod_path, attr_path = provider.split(":", 1)
    obj = importlib.import_module(mod_path)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


class TestAcpContribActionHandlerParity(unittest.TestCase):
    """Ensures every declared ACP action has a callable service handler."""

    def test_declared_actions_have_callable_handlers(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)
        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        AdminRuntimeBinder(registry=registry, rsg=_FakeRsg()).bind_edm_schema()

        service_specs_by_key = {
            spec.service_key: spec for spec in registry.service_specs()
        }
        missing_handlers: list[str] = []

        for resource in registry.resources.values():
            actions = tuple(resource.capabilities.actions.keys())
            if not actions:
                continue

            service_spec = service_specs_by_key.get(resource.service_key)
            if service_spec is None:
                missing_handlers.append(
                    f"{resource.entity_set}: missing service spec for action checks."
                )
                continue

            service_cls = _load_provider_attr(service_spec.service_cls)
            tenant_scoped = (
                registry.schema.get_type(resource.edm_type_name).find_property(
                    "TenantId"
                )
                is not None
            )

            for action in actions:
                if tenant_scoped:
                    expected_handlers = (f"action_{action}",)
                else:
                    expected_handlers = (
                        f"entity_action_{action}",
                        f"entity_set_action_{action}",
                    )

                has_handler = any(
                    callable(getattr(service_cls, handler_name, None))
                    for handler_name in expected_handlers
                )
                if not has_handler:
                    missing_handlers.append(
                        (
                            f"{resource.entity_set}/$action/{action}: expected one of "
                            f"{expected_handlers} on {service_cls.__name__}."
                        )
                    )

        self.assertEqual(
            missing_handlers,
            [],
            msg=(
                "ACP action handler parity failures:\n- "
                + "\n- ".join(missing_handlers)
            ),
        )
