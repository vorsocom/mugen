"""Coverage tests for mugen.core.plugin.context_engine.fw_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mugen.core.plugin.context_engine.fw_ext as fw_ext_module
from mugen.core.plugin.context_engine.fw_ext import ContextEngineFWExtension


class _Registry:
    def __init__(self) -> None:
        self.policy_resolver = None
        self.state_store = None
        self.memory_writer = None
        self.cache = None
        self.trace_sinks: list[object] = []
        self.guards: list[object] = []
        self.rankers: list[object] = []
        self.contributors: list[object] = []

    def set_policy_resolver(self, value) -> None:
        self.policy_resolver = value

    def set_state_store(self, value) -> None:
        self.state_store = value

    def set_memory_writer(self, value) -> None:
        self.memory_writer = value

    def set_cache(self, value) -> None:
        self.cache = value

    def register_trace_sink(self, value) -> None:
        self.trace_sinks.append(value)

    def register_guard(self, value) -> None:
        self.guards.append(value)

    def register_ranker(self, value) -> None:
        self.rankers.append(value)

    def register_contributor(self, value) -> None:
        self.contributors.append(value)


def _ctor(name: str) -> Mock:
    return Mock(name=name, return_value=f"{name}-instance")


class TestMugenContextEngineFWExtension(unittest.IsolatedAsyncioTestCase):
    """Exercise provider, setup, and table-registration paths."""

    async def test_setup_registers_runtime_components_and_ext_service(self) -> None:
        container = SimpleNamespace(
            config=SimpleNamespace(mugen=SimpleNamespace(assistant=SimpleNamespace(persona="hi"))),
            relational_storage_gateway="rsg",
            register_ext_service=Mock(),
        )
        registry = _Registry()

        patches = {
            "ContextProfileService": _ctor("ContextProfileService"),
            "ContextPolicyService": _ctor("ContextPolicyService"),
            "ContextContributorBindingService": _ctor("ContextContributorBindingService"),
            "ContextSourceBindingService": _ctor("ContextSourceBindingService"),
            "ContextTracePolicyService": _ctor("ContextTracePolicyService"),
            "ContextStateSnapshotService": _ctor("ContextStateSnapshotService"),
            "ContextEventLogService": _ctor("ContextEventLogService"),
            "ContextMemoryRecordService": _ctor("ContextMemoryRecordService"),
            "ContextCacheRecordService": _ctor("ContextCacheRecordService"),
            "ContextTraceService": _ctor("ContextTraceService"),
            "KnowledgeScopeService": _ctor("KnowledgeScopeService"),
            "ConversationStateService": _ctor("ConversationStateService"),
            "WorkItemService": _ctor("WorkItemService"),
            "CaseService": _ctor("CaseService"),
            "CaseEventService": _ctor("CaseEventService"),
            "AuditBizTraceEventService": _ctor("AuditBizTraceEventService"),
            "DefaultContextPolicyResolver": _ctor("DefaultContextPolicyResolver"),
            "RelationalContextStateStore": _ctor("RelationalContextStateStore"),
            "DefaultMemoryWriter": _ctor("DefaultMemoryWriter"),
            "RelationalContextCache": _ctor("RelationalContextCache"),
            "RelationalContextTraceSink": _ctor("RelationalContextTraceSink"),
            "DefaultContextGuard": _ctor("DefaultContextGuard"),
            "DefaultContextRanker": _ctor("DefaultContextRanker"),
            "PersonaPolicyContributor": _ctor("PersonaPolicyContributor"),
            "StateContributor": _ctor("StateContributor"),
            "ChannelOrchestrationContributor": _ctor("ChannelOrchestrationContributor"),
            "OpsCaseContributor": _ctor("OpsCaseContributor"),
            "KnowledgePackContributor": _ctor("KnowledgePackContributor"),
            "MemoryContributor": _ctor("MemoryContributor"),
            "AuditContributor": _ctor("AuditContributor"),
            "RecentTurnContributor": _ctor("RecentTurnContributor"),
            "ContextComponentRegistry": Mock(return_value=registry),
        }

        with (
            patch.object(fw_ext_module.di, "container", new=container),
            patch.object(fw_ext_module, "_config_provider", side_effect=lambda: container.config),
            patch.object(fw_ext_module, "_rsg_provider", side_effect=lambda: container.relational_storage_gateway),
            patch.multiple(fw_ext_module, **patches),
        ):
            ext = ContextEngineFWExtension()
            self.assertEqual(ext.platforms, [])
            await ext.setup(app=Mock())

        self.assertEqual(registry.policy_resolver, "DefaultContextPolicyResolver-instance")
        self.assertEqual(registry.state_store, "RelationalContextStateStore-instance")
        self.assertEqual(registry.memory_writer, "DefaultMemoryWriter-instance")
        self.assertEqual(registry.cache, "RelationalContextCache-instance")
        self.assertEqual(registry.trace_sinks, ["RelationalContextTraceSink-instance"])
        self.assertEqual(registry.guards, ["DefaultContextGuard-instance"])
        self.assertEqual(registry.rankers, ["DefaultContextRanker-instance"])
        self.assertEqual(
            registry.contributors,
            [
                "PersonaPolicyContributor-instance",
                "StateContributor-instance",
                "ChannelOrchestrationContributor-instance",
                "OpsCaseContributor-instance",
                "KnowledgePackContributor-instance",
                "MemoryContributor-instance",
                "AuditContributor-instance",
                "RecentTurnContributor-instance",
            ],
        )
        container.register_ext_service.assert_called_once()

    async def test_register_runtime_tables_handles_non_sqla_and_value_error(self) -> None:
        ext = ContextEngineFWExtension(
            config_provider=lambda: SimpleNamespace(),
            rsg_provider=lambda: object(),
        )
        ext._register_runtime_tables()  # pylint: disable=protected-access

        class _Gateway:
            def __init__(self, *, side_effect=None) -> None:
                self.register_tables = Mock(side_effect=side_effect)

        with patch.object(fw_ext_module, "SQLAlchemyRelationalStorageGateway", _Gateway):
            gateway = _Gateway()
            ext = ContextEngineFWExtension(
                config_provider=lambda: SimpleNamespace(),
                rsg_provider=lambda: gateway,
            )
            ext._register_runtime_tables()  # pylint: disable=protected-access
            gateway.register_tables.assert_called_once()

            failing_gateway = _Gateway(side_effect=ValueError("dup"))
            ext = ContextEngineFWExtension(
                config_provider=lambda: SimpleNamespace(),
                rsg_provider=lambda: failing_gateway,
            )
            ext._register_runtime_tables()  # pylint: disable=protected-access
            failing_gateway.register_tables.assert_called_once()
