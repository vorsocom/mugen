"""Unit tests for channel_orchestration ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.channel_orchestration.contrib import contribute
from mugen.core.plugin.channel_orchestration.service.blocklist_entry import (
    BlocklistEntryService,
)
from mugen.core.plugin.channel_orchestration.service.channel_profile import (
    ChannelProfileService,
)
from mugen.core.plugin.channel_orchestration.service.conversation_state import (
    ConversationStateService,
)
from mugen.core.plugin.channel_orchestration.service.ingress_binding import (
    IngressBindingService,
)
from mugen.core.plugin.channel_orchestration.service.intake_rule import (
    IntakeRuleService,
)
from mugen.core.plugin.channel_orchestration.service.orchestration_event import (
    OrchestrationEventService,
)
from mugen.core.plugin.channel_orchestration.service.orchestration_policy import (
    OrchestrationPolicyService,
)
from mugen.core.plugin.channel_orchestration.service.routing_rule import (
    RoutingRuleService,
)
from mugen.core.plugin.channel_orchestration.service.throttle_rule import (
    ThrottleRuleService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestChannelOrchestrationContribBinding(unittest.TestCase):
    """Tests declarative registration and runtime materialization."""

    def test_contrib_and_runtime_binding(self) -> None:
        """Contributor should register resources, schema, and services."""
        admin_ns = AdminNs("com.test.admin")
        registry = AdminRegistry(strict_permission_decls=True)

        for verb in ("read", "create", "update", "delete", "manage"):
            registry.register_permission_type(PermissionTypeDef(admin_ns.ns, verb))
        registry.register_global_role(
            GlobalRoleDef(
                namespace=admin_ns.ns,
                name="administrator",
                display_name="Administrator",
            )
        )

        contribute(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace="com.test.channel_orchestration",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        channel_profiles = registry.get_resource("ChannelProfiles")
        ingress_bindings = registry.get_resource("IngressBindings")
        intake_rules = registry.get_resource("IntakeRules")
        routing_rules = registry.get_resource("RoutingRules")
        policies = registry.get_resource("OrchestrationPolicies")
        states = registry.get_resource("ConversationStates")
        throttles = registry.get_resource("ThrottleRules")
        blocklist = registry.get_resource("BlocklistEntries")
        events = registry.get_resource("OrchestrationEvents")

        self.assertIn("channel_orchestration_channel_profile", fake_rsg.tables)
        self.assertIn("channel_orchestration_ingress_binding", fake_rsg.tables)
        self.assertIn("channel_orchestration_intake_rule", fake_rsg.tables)
        self.assertIn("channel_orchestration_routing_rule", fake_rsg.tables)
        self.assertIn("channel_orchestration_orchestration_policy", fake_rsg.tables)
        self.assertIn("channel_orchestration_conversation_state", fake_rsg.tables)
        self.assertIn("channel_orchestration_throttle_rule", fake_rsg.tables)
        self.assertIn("channel_orchestration_blocklist_entry", fake_rsg.tables)
        self.assertIn("channel_orchestration_orchestration_event", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(channel_profiles.service_key),
            ChannelProfileService,
        )
        self.assertIsInstance(
            registry.get_edm_service(ingress_bindings.service_key),
            IngressBindingService,
        )
        self.assertIsInstance(
            registry.get_edm_service(intake_rules.service_key),
            IntakeRuleService,
        )
        self.assertIsInstance(
            registry.get_edm_service(routing_rules.service_key),
            RoutingRuleService,
        )
        self.assertIsInstance(
            registry.get_edm_service(policies.service_key),
            OrchestrationPolicyService,
        )
        self.assertIsInstance(
            registry.get_edm_service(states.service_key),
            ConversationStateService,
        )
        self.assertIsInstance(
            registry.get_edm_service(throttles.service_key),
            ThrottleRuleService,
        )
        self.assertIsInstance(
            registry.get_edm_service(blocklist.service_key),
            BlocklistEntryService,
        )
        self.assertIsInstance(
            registry.get_edm_service(events.service_key),
            OrchestrationEventService,
        )

        self.assertIn("evaluate_intake", states.capabilities.actions)
        self.assertIn("route", states.capabilities.actions)
        self.assertIn("escalate", states.capabilities.actions)
        self.assertIn("apply_throttle", states.capabilities.actions)
        self.assertIn("set_fallback", states.capabilities.actions)

        self.assertIn("block_sender", blocklist.capabilities.actions)
        self.assertIn("unblock_sender", blocklist.capabilities.actions)

        state_type = registry.schema.get_type("CHANNELORCH.ConversationState")
        self.assertEqual(state_type.entity_set_name, "ConversationStates")

        event_type = registry.schema.get_type("CHANNELORCH.OrchestrationEvent")
        self.assertEqual(event_type.entity_set_name, "OrchestrationEvents")
