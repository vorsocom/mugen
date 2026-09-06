"""Regression tests for agent dispatch and reporting source authorization."""

from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import Forbidden, Conflict, InternalServerError

from mugen.core import di
from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityInvocation,
    CapabilityResult,
)
from mugen.core.plugin.acp.api import action as action_module
from mugen.core.plugin.acp.contract.service.sandbox_enforcer import (
    CapabilityDeniedError,
)
from mugen.core.plugin.acp.utility.resource_access import require_resource_access
from mugen.core.plugin.agent_runtime.service.runtime import (
    ACPActionCapabilityProvider,
    AllowlistExecutionGuard,
)
from mugen.core.plugin.ops_case.api.validation import CaseAssignValidation
from mugen.core.plugin.ops_case.service.case import CaseService
from mugen.core.plugin.ops_reporting.service.export_job import ExportJobService


class TestAgentAndReportingBoundaries(unittest.IsolatedAsyncioTestCase):
    """Exercise real dispatch and lookup boundaries with isolated persistence."""

    def setUp(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.actor_id = uuid.uuid4()
        self.record_id = uuid.uuid4()
        self.user = SimpleNamespace(
            id=self.actor_id,
            deleted_at=None,
            locked_at=None,
            global_roles=[],
        )
        self.users = SimpleNamespace(get_expanded=AsyncMock(return_value=self.user))
        self.authorization = SimpleNamespace(
            has_permission=AsyncMock(return_value=True)
        )
        self.enforcer = SimpleNamespace(require=AsyncMock())
        services = {
            di.EXT_SERVICE_ADMIN_SVC_AUTH: self.authorization,
            di.EXT_SERVICE_ADMIN_SANDBOX_ENFORCER: self.enforcer,
        }
        self.container = SimpleNamespace(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    modules=SimpleNamespace(
                        extensions=[
                            {
                                "type": "fw",
                                "token": "core.fw.acp",
                                "namespace": "admin",
                            }
                        ]
                    )
                )
            ),
            get_required_ext_service=Mock(side_effect=services.__getitem__),
        )
        self.patch = patch.object(di, "container", self.container)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.case_service = object.__new__(CaseService)
        self.case_service._get_for_action = AsyncMock(
            return_value=SimpleNamespace(status="open")
        )
        self.case_service._update_case_with_row_version = AsyncMock()
        self.case_service._record_assignment = AsyncMock(return_value=self.record_id)
        self.case_service._append_case_event = AsyncMock()
        self.action_cap = {
            "schema": CaseAssignValidation,
            "perm": "admin:manage",
            "required_capabilities": ["case.assign"],
        }
        self.resource = SimpleNamespace(
            entity_set="OpsCases",
            edm_type_name="OPSCASE.Case",
            service_key="cases",
            namespace="ops_case",
            perm_obj="ops_case:case",
            permissions=SimpleNamespace(manage="admin:manage", read="admin:read"),
            capabilities=SimpleNamespace(
                allow_read=True, actions={"assign": self.action_cap}
            ),
        )
        self.edm_type = Mock()
        self.registry = SimpleNamespace(
            resources={"OpsCases": self.resource},
            get_resource=Mock(return_value=self.resource),
            get_resource_by_type=Mock(
                return_value=SimpleNamespace(service_key="users")
            ),
            get_edm_service=Mock(
                side_effect=lambda key: (
                    self.users if key == "users" else self.case_service
                )
            ),
            schema=SimpleNamespace(get_type=Mock(return_value=self.edm_type)),
        )
        self.request = SimpleNamespace(
            scope=SimpleNamespace(
                tenant_id=str(self.tenant_id),
                sender_id=str(self.actor_id),
                platform="web",
            ),
            metadata={},
            ingress_metadata={},
            message_id="message-1",
            trace_id="trace-1",
        )
        self.policy = AgentRuntimePolicy(capability_allow=("acp__OpsCases__assign",))
        self.run = SimpleNamespace(policy=self.policy)
        self.provider = ACPActionCapabilityProvider(
            admin_registry=self.registry,
            logging_gateway=Mock(),
        )

    async def _execute(self, **arguments: Any) -> CapabilityResult:
        descriptor = (
            await self.provider.list_capabilities(
                self.request, self.run, policy=self.policy
            )
        )[0]
        invocation = CapabilityInvocation(
            capability_key=descriptor.key,
            arguments={
                "entity_id": str(self.record_id),
                "RowVersion": 1,
                "QueueName": "support",
                **arguments,
            },
        )
        await AllowlistExecutionGuard().validate(
            self.request,
            self.run,
            invocation,
            descriptor,
            policy=self.policy,
        )
        return await self.provider.execute(
            self.request, self.run, invocation, descriptor, policy=self.policy
        )

    async def test_authorized_assignment_binds_actor_and_capability(self) -> None:
        result = await self._execute()
        self.assertTrue(result.ok)
        self.authorization.has_permission.assert_awaited_once_with(
            user_id=self.actor_id,
            permission_object="ops_case:case",
            permission_type="admin:manage",
            tenant_id=self.tenant_id,
            allow_global_admin=False,
        )
        self.enforcer.require.assert_awaited_once()
        self.assertEqual(
            self.enforcer.require.await_args.kwargs["tenant_id"], self.tenant_id
        )
        changes = self.case_service._update_case_with_row_version.await_args.kwargs
        self.assertEqual(changes["changes"]["last_actor_user_id"], self.actor_id)

    async def test_model_cannot_override_actor(self) -> None:
        for field in ("auth_user_id", "AuthUserId"):
            with self.subTest(field=field):
                result = await self._execute(**{field: str(uuid.uuid4())})
                self.assertEqual(
                    result.error_message, "model_actor_override_forbidden"
                )
        self.case_service._get_for_action.assert_not_awaited()

    async def test_non_web_sender_needs_trusted_identity_binding(self) -> None:
        self.request.scope.platform = "matrix"
        result = await self._execute()
        self.assertEqual(result.error_message, "auth_user_id_required")
        self.request.metadata["auth_user_id"] = "invalid"
        result = await self._execute()
        self.assertEqual(result.error_message, "auth_user_id_required")
        self.request.metadata["auth_user_id"] = str(self.actor_id)
        self.assertTrue((await self._execute()).ok)

    async def test_denied_or_unavailable_authorization_stops_assignment(self) -> None:
        self.authorization.has_permission.return_value = False
        self.assertFalse((await self._execute()).ok)
        self.authorization.has_permission.side_effect = RuntimeError("unavailable")
        self.assertFalse((await self._execute()).ok)
        self.case_service._get_for_action.assert_not_awaited()
        self.enforcer.require.assert_not_awaited()

    async def test_required_capability_denial_stops_assignment(self) -> None:
        self.enforcer.require.side_effect = CapabilityDeniedError(
            tenant_id=self.tenant_id,
            plugin_key="ops_case",
            capability="case.assign",
            context={},
        )
        with patch.object(action_module, "emit_audit_event", new=AsyncMock()) as emit:
            self.assertFalse((await self._execute()).ok)
        emit.assert_awaited_once()
        self.case_service._get_for_action.assert_not_awaited()

    async def test_missing_permission_and_mismatched_tenant_are_denied(self) -> None:
        self.action_cap.pop("perm")
        self.assertFalse((await self._execute()).ok)
        self.case_service._get_for_action.assert_not_awaited()
        self.action_cap["perm"] = ""
        self.assertTrue((await self._execute()).ok)
        with self.assertRaises(Forbidden):
            await self.provider._authorize_action(
                request=self.request,
                resource=self.resource,
                action_name="assign",
                actor_id=self.actor_id,
                entity_id=self.record_id,
                validated=SimpleNamespace(tenant_id=uuid.uuid4()),
                payload={},
            )

    async def test_global_resources_and_inactive_actors_are_denied(self) -> None:
        self.edm_type.find_property.return_value = None
        self.assertFalse((await self._execute()).ok)
        self.edm_type.find_property.return_value = Mock()
        for user in (
            None,
            SimpleNamespace(deleted_at="deleted", locked_at=None),
            SimpleNamespace(deleted_at=None, locked_at="locked"),
        ):
            with self.subTest(user=user):
                self.users.get_expanded.return_value = user
                self.assertFalse((await self._execute()).ok)
        self.case_service._get_for_action.assert_not_awaited()

    async def test_admin_actions_require_current_admin_role_and_grants(self) -> None:
        self.action_cap["is_admin_action"] = True
        self.assertFalse((await self._execute()).ok)
        self.user.global_roles = [SimpleNamespace(namespace="admin", name="viewer")]
        self.assertFalse((await self._execute()).ok)
        self.user.global_roles = [
            SimpleNamespace(namespace="admin", name="administrator")
        ]
        self.assertTrue((await self._execute()).ok)
        self.authorization.has_permission.return_value = False
        self.assertFalse((await self._execute()).ok)

    async def test_shared_access_helper_supports_explicit_global_scope(self) -> None:
        await require_resource_access(
            registry=self.registry,
            resource=self.resource,
            auth_user_id=self.actor_id,
            tenant_id=None,
            permission_type="admin:read",
        )
        self.registry.schema.get_type.assert_not_called()
        self.assertIsNone(
            self.authorization.has_permission.await_args.kwargs["tenant_id"]
        )

    async def _fetch_export(self, source: Any) -> dict[str, Any]:
        service = object.__new__(ExportJobService)
        service._registry_provider = lambda: self.registry
        service._resolve_resource_service = Mock(return_value=source)
        return await service._fetch_resource_payload(
            tenant_id=self.tenant_id,
            auth_user_id=self.actor_id,
            entity_set="AuditEvents",
            resource_id=self.record_id,
        )

    async def test_export_requires_source_read_permission_before_lookup(self) -> None:
        source = SimpleNamespace(get=AsyncMock())
        self.authorization.has_permission.return_value = False
        with self.assertRaises(Forbidden):
            await self._fetch_export(source)
        source.get.assert_not_awaited()
        self.assertEqual(
            self.authorization.has_permission.await_args.kwargs["permission_type"],
            "admin:read",
        )
        self.resource.capabilities.allow_read = False
        with self.assertRaises(Forbidden):
            await self._fetch_export(source)
        source.get.assert_not_awaited()

    async def test_export_accepts_exact_tenant_records_without_fallback(self) -> None:
        for row in (
            None,
            SimpleNamespace(id=self.record_id, tenant_id=None),
            SimpleNamespace(id=self.record_id, tenant_id=uuid.uuid4()),
            SimpleNamespace(id=self.record_id),
        ):
            with self.subTest(row=row):
                source = SimpleNamespace(get=AsyncMock(return_value=row))
                with self.assertRaises(Conflict):
                    await self._fetch_export(source)
                source.get.assert_awaited_once_with(
                    {"tenant_id": self.tenant_id, "id": self.record_id}
                )
        source = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=self.record_id, tenant_id=self.tenant_id, meta={"safe": True}
                )
            )
        )
        payload = await self._fetch_export(source)
        self.assertEqual(payload["meta"], {"safe": True})
        self.assertEqual(payload["tenant_id"], str(self.tenant_id))

    async def test_export_lookup_errors_never_retry_without_scope(self) -> None:
        source = SimpleNamespace(get=AsyncMock(side_effect=SQLAlchemyError()))
        with self.assertRaises(InternalServerError):
            await self._fetch_export(source)
        source.get.assert_awaited_once()
        source.get = AsyncMock(side_effect=RuntimeError("unexpected storage error"))
        with self.assertRaises(RuntimeError):
            await self._fetch_export(source)
        source.get.assert_awaited_once()

    async def test_action_enforces_configured_required_schema_binding(self) -> None:
        self.container.config.acp = SimpleNamespace(
            schema_registry=SimpleNamespace(enforce_bindings=True)
        )
        schema_id = uuid.uuid4()
        schemas = SimpleNamespace(
            validate_payload=AsyncMock(return_value=(None, ["ExtraField forbidden"]))
        )
        bindings = SimpleNamespace(
            list_active_bindings=AsyncMock(
                return_value=[
                    SimpleNamespace(schema_definition_id=schema_id, is_required=True)
                ]
            )
        )
        resources = {
            "OpsCases": self.resource,
            "Schemas": SimpleNamespace(service_key="schemas"),
            "SchemaBindings": SimpleNamespace(service_key="bindings"),
        }
        services = {
            "users": self.users,
            "cases": self.case_service,
            "schemas": schemas,
            "bindings": bindings,
        }
        self.registry.get_resource.side_effect = resources.__getitem__
        self.registry.get_edm_service.side_effect = services.__getitem__
        result = await self._execute(ExtraField="untrusted")
        self.assertFalse(result.ok)
        self.assertIn("Schema binding validation failed", result.error_message)
        self.case_service._get_for_action.assert_not_awaited()
        payload = schemas.validate_payload.await_args.kwargs["payload"]
        self.assertEqual(payload["ExtraField"], "untrusted")
        bindings.list_active_bindings.assert_awaited_once_with(
            tenant_id=self.tenant_id,
            target_namespace="ops_case",
            target_entity_set="OpsCases",
            target_action="assign",
            binding_kind="action",
        )
        schemas.validate_payload.return_value = (None, [])
        self.assertTrue((await self._execute()).ok)

    async def test_audit_proof_requires_audit_read_without_resource_reference(
        self,
    ) -> None:
        service = object.__new__(ExportJobService)
        service._registry_provider = lambda: self.registry
        service._audit_event_service = SimpleNamespace(
            action_verify_chain=AsyncMock(return_value=({"CheckedRows": 3}, 200))
        )
        self.authorization.has_permission.return_value = False
        with self.assertRaises(Forbidden):
            await service._build_audit_chain_proof(
                tenant_id=self.tenant_id,
                auth_user_id=self.actor_id,
                proofs_json={"AuditChain": {}},
            )
        self.registry.get_resource.assert_called_with("AuditEvents")
        service._audit_event_service.action_verify_chain.assert_not_awaited()
        self.authorization.has_permission.return_value = True
        proof = await service._build_audit_chain_proof(
            tenant_id=self.tenant_id,
            auth_user_id=self.actor_id,
            proofs_json={"AuditChain": {}},
        )
        self.assertEqual(proof, {"CheckedRows": 3})
