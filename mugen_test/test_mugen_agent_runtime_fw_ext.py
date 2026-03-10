"""Coverage tests for mugen.core.plugin.agent_runtime.fw_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mugen.core.plugin.agent_runtime.fw_ext as fw_ext_module
from mugen.core.plugin.agent_runtime.fw_ext import AgentRuntimeFWExtension


class _Registry:
    def __init__(self) -> None:
        self.policy_resolver = None
        self.run_store = None
        self.scheduler = None
        self.planners: list[object] = []
        self.evaluators: list[object] = []
        self.capability_providers: list[object] = []
        self.execution_guards: list[object] = []
        self.response_synthesizers: list[object] = []

    def set_policy_resolver(self, value, *, owner=None) -> None:
        _ = owner
        self.policy_resolver = value

    def set_run_store(self, value, *, owner=None) -> None:
        _ = owner
        self.run_store = value

    def set_scheduler(self, value, *, owner=None) -> None:
        _ = owner
        self.scheduler = value

    def register_planner(self, value) -> None:
        self.planners.append(value)

    def register_evaluator(self, value) -> None:
        self.evaluators.append(value)

    def register_capability_provider(self, value) -> None:
        self.capability_providers.append(value)

    def register_execution_guard(self, value) -> None:
        self.execution_guards.append(value)

    def register_response_synthesizer(self, value) -> None:
        self.response_synthesizers.append(value)


def _ctor(name: str) -> Mock:
    return Mock(name=name, return_value=f"{name}-instance")


class TestMugenAgentRuntimeFWExtension(unittest.IsolatedAsyncioTestCase):
    """Exercise provider, setup, and table-registration paths."""

    async def test_setup_registers_runtime_components_and_ext_service(self) -> None:
        container = SimpleNamespace(
            config=SimpleNamespace(),
            relational_storage_gateway="rsg",
            completion_gateway="completion-gateway",
            logging_gateway="logging-gateway",
            register_ext_service=Mock(),
            get_ext_service=Mock(return_value="admin-registry"),
        )
        registry = _Registry()

        patches = {
            "AgentPlanRunService": _ctor("AgentPlanRunService"),
            "AgentPlanStepService": _ctor("AgentPlanStepService"),
            "RelationalPlanRunStore": _ctor("RelationalPlanRunStore"),
            "CodeConfiguredAgentPolicyResolver": _ctor(
                "CodeConfiguredAgentPolicyResolver"
            ),
            "RelationalAgentScheduler": _ctor("RelationalAgentScheduler"),
            "LLMPlannerStrategy": _ctor("LLMPlannerStrategy"),
            "LLMEvaluationStrategy": _ctor("LLMEvaluationStrategy"),
            "ACPActionCapabilityProvider": _ctor("ACPActionCapabilityProvider"),
            "AllowlistExecutionGuard": _ctor("AllowlistExecutionGuard"),
            "TextResponseSynthesizer": _ctor("TextResponseSynthesizer"),
            "AgentComponentRegistry": Mock(return_value=registry),
        }

        with (
            patch.object(fw_ext_module.di, "container", new=container),
            patch.multiple(fw_ext_module, **patches),
        ):
            ext = AgentRuntimeFWExtension()
            self.assertEqual(ext.platforms, [])
            await ext.setup(app=Mock())

        self.assertEqual(
            registry.policy_resolver,
            "CodeConfiguredAgentPolicyResolver-instance",
        )
        self.assertEqual(registry.run_store, "RelationalPlanRunStore-instance")
        self.assertEqual(registry.scheduler, "RelationalAgentScheduler-instance")
        self.assertEqual(registry.planners, ["LLMPlannerStrategy-instance"])
        self.assertEqual(registry.evaluators, ["LLMEvaluationStrategy-instance"])
        self.assertEqual(
            registry.capability_providers,
            ["ACPActionCapabilityProvider-instance"],
        )
        self.assertEqual(
            registry.execution_guards,
            ["AllowlistExecutionGuard-instance"],
        )
        self.assertEqual(
            registry.response_synthesizers,
            ["TextResponseSynthesizer-instance"],
        )
        container.register_ext_service.assert_called_once_with(
            fw_ext_module.di.EXT_SERVICE_AGENT_COMPONENT_REGISTRY,
            registry,
            override=True,
        )

    async def test_register_runtime_tables_handles_non_sqla_and_value_error(
        self,
    ) -> None:
        ext = AgentRuntimeFWExtension(
            config_provider=lambda: SimpleNamespace(),
            rsg_provider=lambda: object(),
        )
        ext._register_runtime_tables()  # pylint: disable=protected-access

        class _Gateway:
            def __init__(self, *, side_effect=None) -> None:
                self.register_tables = Mock(side_effect=side_effect)

        with patch.object(
            fw_ext_module,
            "SQLAlchemyRelationalStorageGateway",
            _Gateway,
        ):
            gateway = _Gateway()
            ext = AgentRuntimeFWExtension(
                config_provider=lambda: SimpleNamespace(),
                rsg_provider=lambda: gateway,
            )
            ext._register_runtime_tables()  # pylint: disable=protected-access
            gateway.register_tables.assert_called_once()

            failing_gateway = _Gateway(side_effect=ValueError("dup"))
            ext = AgentRuntimeFWExtension(
                config_provider=lambda: SimpleNamespace(),
                rsg_provider=lambda: failing_gateway,
            )
            ext._register_runtime_tables()  # pylint: disable=protected-access
            failing_gateway.register_tables.assert_called_once()


if __name__ == "__main__":
    unittest.main()
