"""Unit tests for ops_workflow ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_workflow.contrib import contribute
from mugen.core.plugin.ops_workflow.service.workflow_definition import (
    WorkflowDefinitionService,
)
from mugen.core.plugin.ops_workflow.service.workflow_event import WorkflowEventService
from mugen.core.plugin.ops_workflow.service.workflow_instance import (
    WorkflowInstanceService,
)
from mugen.core.plugin.ops_workflow.service.workflow_state import WorkflowStateService
from mugen.core.plugin.ops_workflow.service.workflow_task import WorkflowTaskService
from mugen.core.plugin.ops_workflow.service.workflow_transition import (
    WorkflowTransitionService,
)
from mugen.core.plugin.ops_workflow.service.workflow_version import (
    WorkflowVersionService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsWorkflowContribBinding(unittest.TestCase):
    """Tests ops_workflow declarative registration and runtime materialization."""

    def test_contrib_and_runtime_binding(self) -> None:
        """Contributor should register resources, tables, schema, and services."""
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
            plugin_namespace="com.test.ops_workflow",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        definitions = registry.get_resource("OpsWorkflowDefinitions")
        versions = registry.get_resource("OpsWorkflowVersions")
        states = registry.get_resource("OpsWorkflowStates")
        transitions = registry.get_resource("OpsWorkflowTransitions")
        instances = registry.get_resource("OpsWorkflowInstances")
        tasks = registry.get_resource("OpsWorkflowTasks")
        events = registry.get_resource("OpsWorkflowEvents")

        self.assertIn("ops_workflow_workflow_definition", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_version", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_state", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_transition", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_instance", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_task", fake_rsg.tables)
        self.assertIn("ops_workflow_workflow_event", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(definitions.service_key),
            WorkflowDefinitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(versions.service_key),
            WorkflowVersionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(states.service_key),
            WorkflowStateService,
        )
        self.assertIsInstance(
            registry.get_edm_service(transitions.service_key),
            WorkflowTransitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(instances.service_key),
            WorkflowInstanceService,
        )
        self.assertIsInstance(
            registry.get_edm_service(tasks.service_key),
            WorkflowTaskService,
        )
        self.assertIsInstance(
            registry.get_edm_service(events.service_key),
            WorkflowEventService,
        )

        self.assertIn("start_instance", instances.capabilities.actions)
        self.assertIn("advance", instances.capabilities.actions)
        self.assertIn("approve", instances.capabilities.actions)
        self.assertIn("reject", instances.capabilities.actions)
        self.assertIn("cancel_instance", instances.capabilities.actions)
        self.assertIn("assign_task", tasks.capabilities.actions)
        self.assertIn("complete_task", tasks.capabilities.actions)

        instance_type = registry.schema.get_type("OPSWORKFLOW.WorkflowInstance")
        self.assertEqual(instance_type.entity_set_name, "OpsWorkflowInstances")

        event_type = registry.schema.get_type("OPSWORKFLOW.WorkflowEvent")
        self.assertEqual(event_type.entity_set_name, "OpsWorkflowEvents")
