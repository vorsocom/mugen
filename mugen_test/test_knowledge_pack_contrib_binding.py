"""Unit tests for knowledge_pack ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.knowledge_pack.contrib import contribute
from mugen.core.plugin.knowledge_pack.service.knowledge_approval import (
    KnowledgeApprovalService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry import (
    KnowledgeEntryService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_pack import KnowledgePackService
from mugen.core.plugin.knowledge_pack.service.knowledge_pack_version import (
    KnowledgePackVersionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import (
    KnowledgeScopeService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestKnowledgePackContribBinding(unittest.TestCase):
    """Tests knowledge_pack declarative registration and materialization."""

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
            plugin_namespace="com.test.knowledge_pack",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        packs = registry.get_resource("KnowledgePacks")
        versions = registry.get_resource("KnowledgePackVersions")
        entries = registry.get_resource("KnowledgeEntries")
        revisions = registry.get_resource("KnowledgeEntryRevisions")
        approvals = registry.get_resource("KnowledgeApprovals")
        scopes = registry.get_resource("KnowledgeScopes")

        self.assertIn("knowledge_pack_knowledge_pack", fake_rsg.tables)
        self.assertIn("knowledge_pack_knowledge_pack_version", fake_rsg.tables)
        self.assertIn("knowledge_pack_knowledge_entry", fake_rsg.tables)
        self.assertIn("knowledge_pack_knowledge_entry_revision", fake_rsg.tables)
        self.assertIn("knowledge_pack_knowledge_approval", fake_rsg.tables)
        self.assertIn("knowledge_pack_knowledge_scope", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(packs.service_key),
            KnowledgePackService,
        )
        self.assertIsInstance(
            registry.get_edm_service(versions.service_key),
            KnowledgePackVersionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(entries.service_key),
            KnowledgeEntryService,
        )
        self.assertIsInstance(
            registry.get_edm_service(revisions.service_key),
            KnowledgeEntryRevisionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(approvals.service_key),
            KnowledgeApprovalService,
        )
        self.assertIsInstance(
            registry.get_edm_service(scopes.service_key),
            KnowledgeScopeService,
        )

        self.assertIn("submit_for_review", versions.capabilities.actions)
        self.assertIn("approve", versions.capabilities.actions)
        self.assertIn("reject", versions.capabilities.actions)
        self.assertIn("publish", versions.capabilities.actions)
        self.assertIn("archive", versions.capabilities.actions)
        self.assertIn("rollback_version", versions.capabilities.actions)

        version_type = registry.schema.get_type("KNOWLEDGEPACK.KnowledgePackVersion")
        self.assertEqual(version_type.entity_set_name, "KnowledgePackVersions")

        scope_type = registry.schema.get_type("KNOWLEDGEPACK.KnowledgeScope")
        self.assertEqual(scope_type.entity_set_name, "KnowledgeScopes")
