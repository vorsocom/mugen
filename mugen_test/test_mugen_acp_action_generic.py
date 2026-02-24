"""Unit tests for mugen.core.plugin.acp.api.action."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from quart import Quart

from mugen.core.plugin.acp.api import action as action_api


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


class _ActionPayload(BaseModel):
    row_version: int


class _FakeEdmType:
    def __init__(self, has_tenant: bool):
        self._has_tenant = has_tenant

    def find_property(self, name: str):
        if name == "TenantId" and self._has_tenant:
            return object()
        return None


class _FakeSchema:
    def __init__(self, has_tenant: bool):
        self._type = _FakeEdmType(has_tenant=has_tenant)

    def get_type(self, _edm_name: str):
        return self._type


class _FakeService:
    def __init__(self, *, raise_db_error: bool = False):
        self.raise_db_error = raise_db_error
        self.calls = []

    async def entity_set_action_do(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("entity_set_action_do", kwargs))
        return {"status": "ok-set"}

    async def action_do(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("action_do", kwargs))
        return {"status": "ok-tenant"}

    async def entity_action_do(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("entity_action_do", kwargs))
        return {"status": "ok-entity"}

    async def entity_action_deactivate(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("entity_action_deactivate", kwargs))
        return {"status": "tenant-deactivated"}

    async def entity_action_deprecate(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("entity_action_deprecate", kwargs))
        return {"status": "permission-object-deprecated"}

    async def action_suspend(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("action_suspend", kwargs))
        return {"status": "membership-suspended"}

    async def action_deprecate(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("action_deprecate", kwargs))
        return {"status": "role-deprecated"}

    async def entity_action_revoke(self, **kwargs):
        if self.raise_db_error:
            raise SQLAlchemyError("db")
        self.calls.append(("entity_action_revoke", kwargs))
        return {"status": "refresh-token-revoked"}


class _FakeRegistry:
    def __init__(
        self,
        *,
        has_tenant: bool,
        service: _FakeService,
        schema=_ActionPayload,
        actions=None,
    ):
        self.schema = _FakeSchema(has_tenant=has_tenant)
        self._service = service
        self._resource = SimpleNamespace(
            edm_type_name="ACP.Thing",
            service_key="thing_svc",
            namespace="com.test.plugin",
            capabilities=SimpleNamespace(
                actions=actions or {"do": {"schema": schema}}
            ),
        )

    def get_resource(self, _entity_set: str):
        return self._resource

    def get_edm_service(self, _service_key: str):
        return self._service


class TestMugenAcpActionGeneric(unittest.IsolatedAsyncioTestCase):
    """Covers helper functions and generic action endpoint dispatch branches."""

    async def test_helpers_and_provider_functions(self) -> None:
        # pylint: disable=protected-access
        self.assertEqual(action_api._entity_name("ACP.User"), "User")
        self.assertEqual(action_api._entity_name("User"), "User")

        app = Quart("action_helpers_test")
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        ):
            self.assertEqual(action_api._request_ids(), ("req-1", "corr-1"))

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            headers={"X-Request-Id": "req-2", "X-Trace-Id": "trace-2"},
        ):
            self.assertEqual(action_api._request_ids(), ("req-2", "trace-2"))

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            headers={"X-Request-Id": "req-3"},
        ):
            self.assertEqual(action_api._request_ids(), ("req-3", "req-3"))

        with patch.object(
            action_api.di,
            "container",
            new=SimpleNamespace(
                logging_gateway="logger",
                get_required_ext_service=lambda _key: "registry",
            ),
        ):
            self.assertEqual(action_api._logger_provider(), "logger")
            self.assertEqual(action_api._registry_provider(), "registry")

    async def test_dispatch_entity_set_action_paths(self) -> None:
        app = Quart("action_set_dispatch_test")
        service = _FakeService()
        registry = _FakeRegistry(has_tenant=False, service=service)
        logger = Mock()

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit:
                result = await action_api.dispatch_entity_set_action.__wrapped__(
                    entity_set="Things",
                    action="do",
                    auth_user=str(uuid.uuid4()),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(result, {"status": "ok-set"})
        emit.assert_awaited_once()

        service.raise_db_error = True
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with (
                patch.object(action_api, "abort", side_effect=_abort_raiser),
                patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit,
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=str(uuid.uuid4()),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: registry,
                    )
                self.assertEqual(ex.exception.code, 500)
                emit.assert_awaited_once()

        tenant_registry = _FakeRegistry(has_tenant=True, service=_FakeService())
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=str(uuid.uuid4()),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_dispatch_entity_set_action_tenant_paths(self) -> None:
        app = Quart("action_set_tenant_dispatch_test")
        service = _FakeService()
        registry = _FakeRegistry(has_tenant=True, service=service)
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        logger = Mock()

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 4},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit:
                result = await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                    tenant_id=str(tenant_id),
                    entity_set="Things",
                    action="do",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(result, {"status": "ok-tenant"})
        self.assertEqual(service.calls[-1][1]["where"], {"tenant_id": tenant_id})
        emit.assert_awaited_once()

        non_tenant_registry = _FakeRegistry(has_tenant=False, service=service)
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 4},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=str(tenant_id),
                        entity_set="Things",
                        action="do",
                        auth_user=str(auth_user),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 4},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id="not-a-uuid",
                        entity_set="Things",
                        action="do",
                        auth_user=str(auth_user),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: registry,
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_dispatch_entity_action_and_tenant_paths(self) -> None:
        app = Quart("action_entity_dispatch_test")
        service = _FakeService()
        non_tenant_registry = _FakeRegistry(has_tenant=False, service=service)
        tenant_registry = _FakeRegistry(has_tenant=True, service=service)
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        logger = Mock()

        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action.__wrapped__(
                    entity_set="Things",
                    entity_id=str(entity_id),
                    action="do",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: non_tenant_registry,
                )
        self.assertEqual(result, {"status": "ok-entity"})

        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id="bad-id",
                        action="do",
                        auth_user=str(auth_user),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                tenant_result = (
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=str(tenant_id),
                        entity_set="Things",
                        entity_id=str(entity_id),
                        action="do",
                        auth_user=str(auth_user),
                        logger_provider=lambda: logger,
                        registry_provider=lambda: tenant_registry,
                    )
                )
        self.assertEqual(tenant_result, {"status": "ok-tenant"})

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=str(tenant_id),
                        entity_set="Things",
                        entity_id=str(entity_id),
                        action="do",
                        auth_user="bad-auth-user",
                        logger_provider=lambda: logger,
                        registry_provider=lambda: tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

    async def test_dispatch_resolves_tenant_lifecycle_handler_names(self) -> None:
        app = Quart("action_lifecycle_handlers")
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        service = _FakeService()
        logger = Mock()

        tenant_registry = _FakeRegistry(
            has_tenant=False,
            service=service,
            actions={"deactivate": {"schema": _ActionPayload}},
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/Tenants/{entity_id}/$action/deactivate",
            method="POST",
            json={"row_version": 1},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action.__wrapped__(
                    entity_set="Tenants",
                    entity_id=str(entity_id),
                    action="deactivate",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: tenant_registry,
                )
        self.assertEqual(result, {"status": "tenant-deactivated"})
        self.assertEqual(service.calls[-1][0], "entity_action_deactivate")

        permission_object_registry = _FakeRegistry(
            has_tenant=False,
            service=service,
            actions={"deprecate": {"schema": _ActionPayload}},
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/PermissionObjects/{entity_id}/$action/deprecate",
            method="POST",
            json={"row_version": 1},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action.__wrapped__(
                    entity_set="PermissionObjects",
                    entity_id=str(entity_id),
                    action="deprecate",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: permission_object_registry,
                )
        self.assertEqual(result, {"status": "permission-object-deprecated"})
        self.assertEqual(service.calls[-1][0], "entity_action_deprecate")

        refresh_token_registry = _FakeRegistry(
            has_tenant=False,
            service=service,
            actions={"revoke": {"schema": _ActionPayload}},
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/RefreshTokens/{entity_id}/$action/revoke",
            method="POST",
            json={"row_version": 1},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action.__wrapped__(
                    entity_set="RefreshTokens",
                    entity_id=str(entity_id),
                    action="revoke",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: refresh_token_registry,
                )
        self.assertEqual(result, {"status": "refresh-token-revoked"})
        self.assertEqual(service.calls[-1][0], "entity_action_revoke")

        role_registry = _FakeRegistry(
            has_tenant=True,
            service=service,
            actions={"deprecate": {"schema": _ActionPayload}},
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Roles/{entity_id}/$action/deprecate",
            method="POST",
            json={"row_version": 2},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action_tenant.__wrapped__(
                    tenant_id=str(tenant_id),
                    entity_set="Roles",
                    entity_id=str(entity_id),
                    action="deprecate",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: role_registry,
                )
        self.assertEqual(result, {"status": "role-deprecated"})
        self.assertEqual(service.calls[-1][0], "action_deprecate")

        membership_registry = _FakeRegistry(
            has_tenant=True,
            service=service,
            actions={"suspend": {"schema": _ActionPayload}},
        )
        async with app.test_request_context(
            (
                f"/api/core/acp/v1/tenants/{tenant_id}/TenantMemberships/"
                f"{entity_id}/$action/suspend"
            ),
            method="POST",
            json={"row_version": 2},
        ):
            with patch.object(action_api, "emit_audit_event", new=AsyncMock()):
                result = await action_api.dispatch_entity_action_tenant.__wrapped__(
                    tenant_id=str(tenant_id),
                    entity_set="TenantMemberships",
                    entity_id=str(entity_id),
                    action="suspend",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: membership_registry,
                )
        self.assertEqual(result, {"status": "membership-suspended"})
        self.assertEqual(service.calls[-1][0], "action_suspend")

    async def test_dispatch_entity_set_action_error_branches(self) -> None:
        app = Quart("action_set_dispatch_errors")
        logger = Mock()
        auth_user = str(uuid.uuid4())

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json=["not-a-dict"],
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)
        logger.debug.assert_called()

        missing_handler_registry = _FakeRegistry(
            has_tenant=False,
            service=SimpleNamespace(),
        )
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        non_callable_handler_registry = _FakeRegistry(
            has_tenant=False,
            service=SimpleNamespace(entity_set_action_do="nope"),
        )
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_callable_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user="bad-auth-user",
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called()

        missing_schema_registry = _FakeRegistry(
            has_tenant=False,
            service=_FakeService(),
            schema=None,
        )
        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_schema_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            "/api/core/acp/v1/Things/$action/do",
            method="POST",
            json={},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action.__wrapped__(
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_dispatch_entity_set_action_tenant_error_branches(self) -> None:
        app = Quart("action_set_tenant_dispatch_errors")
        logger = Mock()
        tenant_id = str(uuid.uuid4())
        auth_user = str(uuid.uuid4())

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json=["not-a-dict"],
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        missing_handler_registry = _FakeRegistry(
            has_tenant=True,
            service=SimpleNamespace(),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        non_callable_handler_registry = _FakeRegistry(
            has_tenant=True,
            service=SimpleNamespace(action_do="nope"),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_callable_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user="bad-auth-user",
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 500)

        missing_schema_registry = _FakeRegistry(
            has_tenant=True,
            service=_FakeService(),
            schema=None,
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_schema_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        db_error_registry = _FakeRegistry(
            has_tenant=True,
            service=_FakeService(raise_db_error=True),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/$action/do",
            method="POST",
            json={"row_version": 3},
        ):
            with (
                patch.object(action_api, "abort", side_effect=_abort_raiser),
                patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit,
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_set_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: db_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)
                emit.assert_awaited_once()

    async def test_dispatch_entity_action_error_branches(self) -> None:
        app = Quart("action_entity_dispatch_errors")
        logger = Mock()
        auth_user = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())

        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json=["not-a-dict"],
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        tenant_registry = _FakeRegistry(has_tenant=True, service=_FakeService())
        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        missing_handler_registry = _FakeRegistry(
            has_tenant=False,
            service=SimpleNamespace(),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        non_callable_handler_registry = _FakeRegistry(
            has_tenant=False,
            service=SimpleNamespace(entity_action_do="nope"),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_callable_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user="bad-auth-user",
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 500)

        missing_schema_registry = _FakeRegistry(
            has_tenant=False,
            service=_FakeService(),
            schema=None,
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_schema_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=False,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        db_error_registry = _FakeRegistry(
            has_tenant=False,
            service=_FakeService(raise_db_error=True),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with (
                patch.object(action_api, "abort", side_effect=_abort_raiser),
                patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit,
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action.__wrapped__(
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: db_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)
                emit.assert_awaited_once()

    async def test_dispatch_entity_action_tenant_error_branches(self) -> None:
        app = Quart("action_entity_tenant_dispatch_errors")
        logger = Mock()
        tenant_id = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        auth_user = str(uuid.uuid4())

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json=["not-a-dict"],
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        non_tenant_registry = _FakeRegistry(has_tenant=False, service=_FakeService())
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        async with app.test_request_context(
            "/api/core/acp/v1/tenants/not-a-uuid/Things/123/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id="not-a-uuid",
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/not-a-uuid/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id="not-a-uuid",
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        missing_handler_registry = _FakeRegistry(
            has_tenant=True,
            service=SimpleNamespace(),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        non_callable_handler_registry = _FakeRegistry(
            has_tenant=True,
            service=SimpleNamespace(action_do="nope"),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: non_callable_handler_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        missing_schema_registry = _FakeRegistry(
            has_tenant=True,
            service=_FakeService(),
            schema=None,
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: missing_schema_registry,
                    )
                self.assertEqual(ex.exception.code, 501)

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={},
        ):
            with patch.object(action_api, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: _FakeRegistry(
                            has_tenant=True,
                            service=_FakeService(),
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

        db_error_registry = _FakeRegistry(
            has_tenant=True,
            service=_FakeService(raise_db_error=True),
        )
        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Things/{entity_id}/$action/do",
            method="POST",
            json={"row_version": 5},
        ):
            with (
                patch.object(action_api, "abort", side_effect=_abort_raiser),
                patch.object(action_api, "emit_audit_event", new=AsyncMock()) as emit,
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await action_api.dispatch_entity_action_tenant.__wrapped__(
                        tenant_id=tenant_id,
                        entity_set="Things",
                        entity_id=entity_id,
                        action="do",
                        auth_user=auth_user,
                        logger_provider=lambda: logger,
                        registry_provider=lambda: db_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)
                emit.assert_awaited_once()
