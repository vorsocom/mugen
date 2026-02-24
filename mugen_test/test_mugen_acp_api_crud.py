"""Unit tests for mugen.core.plugin.acp.api.crud."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
from datetime import datetime, timezone
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from pydantic import BaseModel
from quart import Quart
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


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
            logging_gateway=SimpleNamespace(
                debug=lambda *_: None,
                error=lambda *_: None,
                warning=lambda *_: None,
            ),
            get_ext_service=lambda *_: None,
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.api import crud as crud_mod
from mugen.core.plugin.acp.contract.sdk.resource import SoftDeleteMode


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class _CreateSchema(BaseModel):
    name: str
    tenant_id: uuid.UUID | None = None


class _UpdateSchema(BaseModel):
    display_name: str | None = None
    tenant_id: uuid.UUID | None = None


class _FakeEdmType:
    def __init__(self, *, tenant_scope: str):
        self._tenant_scope = tenant_scope

    def find_property(self, name: str):
        if name != "TenantId":
            return None

        if self._tenant_scope == "none":
            return None

        if self._tenant_scope == "optional":
            return SimpleNamespace(nullable=True)

        return SimpleNamespace(nullable=False)


def _resolve_scope(
    *,
    tenant_scoped: bool | None = None,
    tenant_scope: str | None = None,
) -> str:
    if tenant_scope is not None:
        return tenant_scope

    if tenant_scoped is None:
        return "none"

    return "required" if tenant_scoped else "none"


class _FakeSchema:
    def __init__(
        self,
        *,
        tenant_scoped: bool | None = None,
        tenant_scope: str | None = None,
    ):
        self._tenant_scope = _resolve_scope(
            tenant_scoped=tenant_scoped,
            tenant_scope=tenant_scope,
        )

    def get_type(self, _edm_type_name: str):
        return _FakeEdmType(tenant_scope=self._tenant_scope)


def _resource(
    *,
    create_schema=None,
    update_schema=None,
    edm_type_name: str = "ACP.User",
    soft_delete_mode: SoftDeleteMode = SoftDeleteMode.TIMESTAMP,
    allow_restore: bool = True,
    soft_delete_column: str = "DeletedAt",
):
    return SimpleNamespace(
        edm_type_name=edm_type_name,
        service_key="user_svc",
        namespace="com.test.acp",
        crud=SimpleNamespace(
            create_schema=create_schema,
            update_schema=update_schema,
        ),
        behavior=SimpleNamespace(
            soft_delete=SimpleNamespace(
                mode=soft_delete_mode,
                allow_restore=allow_restore,
                column=soft_delete_column,
            )
        ),
    )


class _FakeRegistry:
    def __init__(
        self,
        *,
        resource,
        service,
        tenant_scoped: bool | None = True,
        tenant_scope: str | None = None,
    ):
        self._resource = resource
        self._service = service
        self.schema = _FakeSchema(
            tenant_scoped=tenant_scoped,
            tenant_scope=tenant_scope,
        )

    def get_resource(self, _entity_set: str):
        return self._resource

    def get_edm_service(self, _service_key: str):
        return self._service


def _logger():
    return SimpleNamespace(
        debug=Mock(),
        error=Mock(),
        warning=Mock(),
    )


class TestMugenAcpApiCrud(unittest.IsolatedAsyncioTestCase):
    """Covers helper branches and endpoint flows in CRUD API handlers."""

    async def asyncSetUp(self) -> None:
        self.app = Quart("test-acp-api-crud")

    def test_provider_and_helper_functions(self) -> None:
        container = SimpleNamespace(
            logging_gateway="logger",
            get_required_ext_service=Mock(return_value="registry"),
        )
        with patch.object(crud_mod.di, "container", new=container):
            self.assertEqual(crud_mod._logger_provider(), "logger")
            self.assertEqual(crud_mod._registry_provider(), "registry")

        good_id = uuid.uuid4()
        self.assertEqual(crud_mod._parse_uuid_or_none(str(good_id)), good_id)
        self.assertIsNone(crud_mod._parse_uuid_or_none(None))
        self.assertIsNone(crud_mod._parse_uuid_or_none("bad-uuid"))

        self.assertEqual(crud_mod._entity_name("ACP.User"), "User")
        self.assertEqual(crud_mod._entity_name("User"), "User")
        self.assertEqual(
            crud_mod._tenant_scope_mode(
                registry=_FakeRegistry(
                    resource=_resource(),
                    service=SimpleNamespace(),
                    tenant_scope="none",
                ),
                edm_type_name="ACP.User",
            ),
            "none",
        )
        self.assertEqual(
            crud_mod._tenant_scope_mode(
                registry=_FakeRegistry(
                    resource=_resource(),
                    service=SimpleNamespace(),
                    tenant_scope="required",
                ),
                edm_type_name="ACP.User",
            ),
            "required",
        )
        self.assertEqual(
            crud_mod._tenant_scope_mode(
                registry=_FakeRegistry(
                    resource=_resource(),
                    service=SimpleNamespace(),
                    tenant_scope="optional",
                ),
                edm_type_name="ACP.User",
            ),
            "optional",
        )

        duplicate_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("duplicate key value violates unique constraint"),
            None,
        )
        status_code, _ = crud_mod._classify_integrity_error(duplicate_error)
        self.assertEqual(status_code, 409)

        foreign_key_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("insert violates foreign key constraint"),
            None,
        )
        status_code, _ = crud_mod._classify_integrity_error(foreign_key_error)
        self.assertEqual(status_code, 400)

        pgcode_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        pgcode_error.orig = SimpleNamespace(pgcode="23505")
        self.assertEqual(crud_mod._integrity_sql_state(pgcode_error), "23505")
        status_code, _ = crud_mod._classify_integrity_error(pgcode_error)
        self.assertEqual(status_code, 409)

        sqlstate_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        sqlstate_error.orig = SimpleNamespace(sqlstate="23503")
        self.assertEqual(crud_mod._integrity_sql_state(sqlstate_error), "23503")
        status_code, _ = crud_mod._classify_integrity_error(sqlstate_error)
        self.assertEqual(status_code, 400)

        diag_sqlstate_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        diag_sqlstate_error.orig = SimpleNamespace(
            pgcode=None,
            sqlstate=None,
            diag=SimpleNamespace(sqlstate="23514"),
        )
        self.assertEqual(crud_mod._integrity_sql_state(diag_sqlstate_error), "23514")

        diag_missing_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        diag_missing_error.orig = SimpleNamespace(pgcode=None, sqlstate=None, diag=None)
        self.assertIsNone(crud_mod._integrity_sql_state(diag_missing_error))

        diag_non_str_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        diag_non_str_error.orig = SimpleNamespace(
            pgcode=None,
            sqlstate=None,
            diag=SimpleNamespace(sqlstate=12345),
        )
        self.assertIsNone(crud_mod._integrity_sql_state(diag_non_str_error))

        no_orig_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected"),
            None,
        )
        no_orig_error.orig = None
        self.assertIsNone(crud_mod._integrity_sql_state(no_orig_error))

        unknown_integrity_error = IntegrityError(
            "insert into t values (?)",
            {"id": 1},
            Exception("unexpected integrity failure"),
            None,
        )
        unknown_integrity_error.orig = SimpleNamespace(
            pgcode=None,
            sqlstate=None,
            diag=SimpleNamespace(sqlstate=None),
        )
        status_code, _ = crud_mod._classify_integrity_error(unknown_integrity_error)
        self.assertEqual(status_code, 500)

        outcome, status_code, _ = crud_mod._classify_create_update_error(
            duplicate_error
        )
        self.assertEqual(outcome, "conflict")
        self.assertEqual(status_code, 409)

        outcome, status_code, _ = crud_mod._classify_create_update_error(
            foreign_key_error
        )
        self.assertEqual(outcome, "invalid")
        self.assertEqual(status_code, 400)

        outcome, status_code, _ = crud_mod._classify_create_update_error(
            unknown_integrity_error
        )
        self.assertEqual(outcome, "error")
        self.assertEqual(status_code, 500)

        outcome, status_code, _ = crud_mod._classify_create_update_error(
            SQLAlchemyError("boom")
        )
        self.assertEqual(outcome, "error")
        self.assertEqual(status_code, 500)

    async def test_request_ids_and_build_create_data_paths(self) -> None:
        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        ):
            self.assertEqual(crud_mod._request_ids(), ("req-1", "corr-1"))

        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-2", "X-Trace-Id": "trace-2"},
        ):
            self.assertEqual(crud_mod._request_ids(), ("req-2", "trace-2"))

        self.assertEqual(
            crud_mod._build_create_data({"Name": "Alice"}, None, tenant_scoped=False),
            {},
        )

        create_data = crud_mod._build_create_data(
            {"Name": "Alice", "TenantId": str(uuid.uuid4())},
            ("Name", "TenantId"),
            tenant_scoped=True,
        )
        self.assertEqual(create_data, {"name": "Alice"})

        typed_data = crud_mod._build_create_data(
            {"name": "Bob", "tenant_id": str(uuid.uuid4())},
            _CreateSchema,
            tenant_scoped=True,
        )
        self.assertEqual(typed_data, {"name": "Bob"})

        tenant_id = uuid.uuid4()
        typed_data_with_tenant = crud_mod._build_create_data(
            {"name": "Bob", "tenant_id": str(tenant_id)},
            _CreateSchema,
            tenant_scoped=False,
        )
        self.assertEqual(
            typed_data_with_tenant,
            {"name": "Bob", "tenant_id": tenant_id},
        )

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._build_create_data({}, ("Name",), tenant_scoped=False)
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._build_create_data({}, _CreateSchema, tenant_scoped=False)
            self.assertEqual(ex.exception.code, 400)

        update_data = crud_mod._build_update_data(
            {"DisplayName": "Alice"},
            ("DisplayName",),
            tenant_scoped=False,
        )
        self.assertEqual(update_data, {"display_name": "Alice"})

        typed_update = crud_mod._build_update_data(
            {"display_name": "Alice", "tenant_id": str(uuid.uuid4())},
            _UpdateSchema,
            tenant_scoped=True,
        )
        self.assertEqual(typed_update, {"display_name": "Alice"})

        typed_update_non_tenant = crud_mod._build_update_data(
            {"display_name": "Alice"},
            _UpdateSchema,
            tenant_scoped=False,
        )
        self.assertEqual(typed_update_non_tenant, {"display_name": "Alice"})

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._build_update_data(
                    {"tenant_id": "bad-uuid"},
                    _UpdateSchema,
                    tenant_scoped=False,
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_action_only_status_patch(
                    resource=_resource(edm_type_name="ACP.Tenant"),
                    data={"Status": "suspended"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_action_only_status_patch(
                    resource=_resource(edm_type_name="ACP.TenantMembership"),
                    data={"status": "active"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_action_only_status_patch(
                    resource=_resource(edm_type_name="ACP.Role"),
                    data={"Status": "deprecated"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_action_only_status_patch(
                    resource=_resource(edm_type_name="ACP.PermissionObject"),
                    data={"Status": "deprecated"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_action_only_status_patch(
                    resource=_resource(edm_type_name="ACP.PermissionType"),
                    data={"status": "deprecated"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_rbac_immutable_patch_fields(
                    resource=_resource(edm_type_name="ACP.GlobalRole"),
                    data={"Name": "new-name"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_rbac_immutable_patch_fields(
                    resource=_resource(edm_type_name="ACP.Role"),
                    data={"namespace": "new-namespace"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_rbac_immutable_patch_fields(
                    resource=_resource(edm_type_name="ACP.GlobalPermissionEntry"),
                    data={"PermissionObjectId": str(uuid.uuid4())},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                crud_mod._reject_rbac_immutable_patch_fields(
                    resource=_resource(edm_type_name="ACP.PermissionEntry"),
                    data={"role_id": str(uuid.uuid4())},
                )
            self.assertEqual(ex.exception.code, 400)

            crud_mod._reject_rbac_immutable_patch_fields(
                resource=_resource(edm_type_name="ACP.Role"),
                data={"DisplayName": "Allowed"},
            )

            crud_mod._reject_rbac_immutable_patch_fields(
                resource=_resource(edm_type_name="ACP.PermissionEntry"),
                data={"Permitted": True},
            )

            crud_mod._reject_rbac_immutable_patch_fields(
                resource=_resource(edm_type_name="ACP.GlobalPermissionEntry"),
                data={"Permitted": False},
            )

            crud_mod._reject_action_only_status_patch(
                resource=_resource(edm_type_name="ACP.User"),
                data={"Status": "active"},
            )

            crud_mod._reject_rbac_immutable_patch_fields(
                resource=_resource(edm_type_name="ACP.User"),
                data={"Name": "Allowed"},
            )

    async def test_get_entities_and_get_entities_tenant_paths(self) -> None:
        logger = _logger()
        get_entities_fn = crud_mod.get_entities.__wrapped__.__wrapped__

        rows = [{"Id": "1", "Name": "Alice"}]
        payload = await get_entities_fn(
            entity_set="Users",
            entity_id=None,
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=1, values=rows),
            logger_provider=lambda: logger,
        )
        self.assertEqual(payload["@context"], "_#Users")
        self.assertEqual(payload["@count"], 1)
        self.assertEqual(payload["value"], rows)

        payload = await get_entities_fn(
            entity_set="Users",
            entity_id=None,
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=None, values=rows),
            logger_provider=lambda: logger,
        )
        self.assertNotIn("@count", payload)
        self.assertEqual(payload["value"], rows)

        payload = await get_entities_fn(
            entity_set="Users",
            entity_id=str(uuid.uuid4()),
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=None, values=rows),
            logger_provider=lambda: logger,
        )
        self.assertEqual(payload["@context"], "_#Users/$entity")
        self.assertEqual(payload["Name"], "Alice")

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await get_entities_fn(
                    entity_set="Users",
                    entity_id="missing",
                    edm_type_name="ACP.User",
                    rgql=SimpleNamespace(values=[]),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 404)

        get_entities_tenant_fn = crud_mod.get_entities_tenant.__wrapped__.__wrapped__
        registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(),
            tenant_scoped=True,
        )
        tenant_payload = await get_entities_tenant_fn(
            entity_set="Users",
            entity_id=None,
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=0, values=[]),
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertEqual(tenant_payload["@context"], "_#Users")

        optional_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(),
            tenant_scope="optional",
        )
        optional_payload = await get_entities_tenant_fn(
            entity_set="Users",
            entity_id=None,
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=0, values=[]),
            logger_provider=lambda: logger,
            registry_provider=lambda: optional_registry,
        )
        self.assertEqual(optional_payload["@context"], "_#Users")

        tenant_payload = await get_entities_tenant_fn(
            entity_set="Users",
            entity_id=None,
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=None, values=rows),
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertNotIn("@count", tenant_payload)
        self.assertEqual(tenant_payload["value"], rows)

        tenant_payload = await get_entities_tenant_fn(
            entity_set="Users",
            entity_id=str(uuid.uuid4()),
            edm_type_name="ACP.User",
            rgql=SimpleNamespace(count=None, values=rows),
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertEqual(tenant_payload["@context"], "_#Users/$entity")
        self.assertEqual(tenant_payload["Name"], "Alice")

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await get_entities_tenant_fn(
                    entity_set="Users",
                    entity_id="missing",
                    edm_type_name="ACP.User",
                    rgql=SimpleNamespace(values=[]),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 404)

        bad_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(),
            tenant_scoped=False,
        )
        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await get_entities_tenant_fn(
                    entity_set="Users",
                    entity_id=None,
                    edm_type_name="ACP.User",
                    rgql=SimpleNamespace(count=0, values=[]),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: bad_registry,
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_create_entity_paths(self) -> None:
        actor_id = uuid.uuid4()
        created_id = uuid.uuid4()

        svc = SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=created_id))
        )
        registry = _FakeRegistry(
            resource=_resource(create_schema=("Name",)),
            service=svc,
        )
        emit = AsyncMock(return_value=None)
        create_fn = crud_mod.create_entity.__wrapped__

        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            method="POST",
            json={"Name": "Alice"},
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        ):
            with patch.object(crud_mod, "emit_audit_event", new=emit):
                _, status = await create_fn(
                    entity_set="Users",
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 201)
        self.assertEqual(svc.create.await_args.args[0], {"name": "Alice"})
        self.assertEqual(emit.await_args.kwargs["outcome"], "success")

        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            method="POST",
            json=["bad"],
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        failing = SimpleNamespace(create=AsyncMock(side_effect=SQLAlchemyError("boom")))
        fail_registry = _FakeRegistry(
            resource=_resource(create_schema=("Name",)),
            service=failing,
        )
        emit = AsyncMock(return_value=None)
        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with (
                patch.object(crud_mod, "emit_audit_event", new=emit),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: fail_registry,
                    )
                self.assertEqual(ex.exception.code, 500)
        self.assertEqual(emit.await_args.kwargs["outcome"], "error")

        unique_registry = _FakeRegistry(
            resource=_resource(create_schema=("Name",)),
            service=SimpleNamespace(
                create=AsyncMock(
                    side_effect=IntegrityError(
                        "insert",
                        {"name": "Alice"},
                        Exception("duplicate key value violates unique constraint"),
                        None,
                    )
                )
            ),
        )
        emit = AsyncMock(return_value=None)
        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with (
                patch.object(crud_mod, "emit_audit_event", new=emit),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: unique_registry,
                    )
                self.assertEqual(ex.exception.code, 409)
        self.assertEqual(emit.await_args.kwargs["outcome"], "conflict")

        invalid_registry = _FakeRegistry(
            resource=_resource(create_schema=("Name",)),
            service=SimpleNamespace(
                create=AsyncMock(
                    side_effect=IntegrityError(
                        "insert",
                        {"name": "Alice"},
                        Exception("insert violates foreign key constraint"),
                        None,
                    )
                )
            ),
        )
        emit = AsyncMock(return_value=None)
        async with self.app.test_request_context(
            "/api/core/acp/v1/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with (
                patch.object(crud_mod, "emit_audit_event", new=emit),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: invalid_registry,
                    )
                self.assertEqual(ex.exception.code, 400)
        self.assertEqual(emit.await_args.kwargs["outcome"], "invalid")

    async def test_create_entity_tenant_paths(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        svc = SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        )
        registry = _FakeRegistry(
            resource=_resource(create_schema=("TenantId", "Name")),
            service=svc,
            tenant_scoped=True,
        )
        create_fn = crud_mod.create_entity_tenant.__wrapped__

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await create_fn(
                    tenant_id=str(tenant_id),
                    entity_set="Users",
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 201)
        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["name"], "Alice")

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice", "TenantId": str(tenant_id)},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await create_fn(
                    tenant_id=str(tenant_id),
                    entity_set="Users",
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 201)
        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["name"], "Alice")

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice", "TenantId": str(uuid.uuid4())},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        invitation_svc = SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        )
        invitation_registry = _FakeRegistry(
            resource=_resource(
                create_schema=("TenantId", "Email"),
                edm_type_name="ACP.TenantInvitation",
            ),
            service=invitation_svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/TenantInvitations",
            method="POST",
            json={"Email": "invitee@example.com"},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await create_fn(
                    tenant_id=str(tenant_id),
                    entity_set="TenantInvitations",
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: invitation_registry,
                )
        self.assertEqual(status, 201)
        payload = invitation_svc.create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["invited_by_user_id"], actor_id)

        bad_registry = _FakeRegistry(
            resource=_resource(create_schema=("TenantId", "Name")),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: bad_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        integrity_registry = _FakeRegistry(
            resource=_resource(create_schema=("TenantId", "Name")),
            service=SimpleNamespace(
                create=AsyncMock(
                    side_effect=IntegrityError(
                        "insert",
                        {"name": "Alice"},
                        Exception("duplicate key value violates unique constraint"),
                        None,
                    )
                )
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: integrity_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

    async def test_update_entity_and_update_entity_tenant_paths(self) -> None:
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        before = SimpleNamespace(id=entity_id, display_name="old")
        after = SimpleNamespace(id=entity_id, display_name="new")

        svc = SimpleNamespace(
            get=AsyncMock(return_value=before),
            update_with_row_version=AsyncMock(return_value=after),
        )
        registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=svc,
            tenant_scoped=True,
        )
        update_fn = crud_mod.update_entity.__wrapped__
        emit = AsyncMock(return_value=None)

        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7, "DisplayName": "new"},
        ):
            with patch.object(crud_mod, "emit_audit_event", new=emit):
                _, status = await update_fn(
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 204)
        self.assertEqual(
            svc.update_with_row_version.await_args.kwargs["changes"],
            {"display_name": "new"},
        )
        self.assertEqual(emit.await_args.kwargs["outcome"], "success")

        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7},
        ):
            _, status = await update_fn(
                entity_set="Users",
                entity_id=str(entity_id),
                auth_user=str(actor_id),
                logger_provider=_logger,
                registry_provider=lambda: registry,
            )
        self.assertEqual(status, 204)

        conflict_svc = SimpleNamespace(
            get=AsyncMock(return_value=before),
            update_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv")),
        )
        conflict_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=conflict_svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        integrity_conflict_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=before),
                update_with_row_version=AsyncMock(
                    side_effect=IntegrityError(
                        "update",
                        {"display_name": "new"},
                        Exception("duplicate key value violates unique constraint"),
                        None,
                    )
                ),
            ),
            tenant_scoped=True,
        )
        emit = AsyncMock(return_value=None)
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7, "DisplayName": "new"},
        ):
            with (
                patch.object(crud_mod, "emit_audit_event", new=emit),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: integrity_conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)
        self.assertEqual(emit.await_args.kwargs["outcome"], "conflict")

        integrity_invalid_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=before),
                update_with_row_version=AsyncMock(
                    side_effect=IntegrityError(
                        "update",
                        {"display_name": "new"},
                        Exception("update violates foreign key constraint"),
                        None,
                    )
                ),
            ),
            tenant_scoped=True,
        )
        emit = AsyncMock(return_value=None)
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7, "DisplayName": "new"},
        ):
            with (
                patch.object(crud_mod, "emit_audit_event", new=emit),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: integrity_invalid_registry,
                    )
                self.assertEqual(ex.exception.code, 400)
        self.assertEqual(emit.await_args.kwargs["outcome"], "invalid")

        update_tenant_fn = crud_mod.update_entity_tenant.__wrapped__
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "DisplayName": "next"},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await update_tenant_fn(
                    tenant_id=str(tenant_id),
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 204)

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "TenantId": str(tenant_id), "DisplayName": "next"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        tenant_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("Name", "Status"),
                edm_type_name="ACP.Tenant",
            ),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Tenants/{entity_id}",
            method="PATCH",
            json={"RowVersion": 7, "Status": "suspended"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Tenants",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: tenant_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        permission_object_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("Name", "Status"),
                edm_type_name="ACP.PermissionObject",
            ),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/PermissionObjects/{entity_id}",
            method="PATCH",
            json={"RowVersion": 9, "Status": "deprecated"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="PermissionObjects",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: permission_object_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        permission_type_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("Name", "Status"),
                edm_type_name="ACP.PermissionType",
            ),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/PermissionTypes/{entity_id}",
            method="PATCH",
            json={"RowVersion": 9, "Status": "deprecated"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="PermissionTypes",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: permission_type_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        membership_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("RoleInTenant", "Status"),
                edm_type_name="ACP.TenantMembership",
            ),
            service=svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/TenantMemberships/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "Status": "active"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="TenantMemberships",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: membership_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        role_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("DisplayName", "Status"),
                edm_type_name="ACP.Role",
            ),
            service=svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Roles/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "Status": "deprecated"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Roles",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: role_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        global_role_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("DisplayName",),
                edm_type_name="ACP.GlobalRole",
            ),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/GlobalRoles/{entity_id}",
            method="PATCH",
            json={"RowVersion": 9, "Name": "renamed"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="GlobalRoles",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: global_role_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        role_key_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("DisplayName",),
                edm_type_name="ACP.Role",
            ),
            service=svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Roles/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "Namespace": "changed"},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Roles",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: role_key_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        permission_entry_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("Permitted",),
                edm_type_name="ACP.PermissionEntry",
            ),
            service=svc,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/PermissionEntries/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "RoleId": str(uuid.uuid4())},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="PermissionEntries",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: permission_entry_resource_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        global_permission_entry_resource_registry = _FakeRegistry(
            resource=_resource(
                update_schema=("Permitted",),
                edm_type_name="ACP.GlobalPermissionEntry",
            ),
            service=svc,
            tenant_scoped=False,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/GlobalPermissionEntries/{entity_id}",
            method="PATCH",
            json={"RowVersion": 8, "GlobalRoleId": str(uuid.uuid4())},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="GlobalPermissionEntries",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=(
                            lambda: global_permission_entry_resource_registry
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_delete_entity_and_delete_entity_tenant_paths(self) -> None:
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        deleted = SimpleNamespace(id=entity_id)
        svc = SimpleNamespace(delete_with_row_version=AsyncMock(return_value=deleted))
        registry = _FakeRegistry(resource=_resource(), service=svc, tenant_scoped=True)
        delete_fn = crud_mod.delete_entity.__wrapped__

        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 9},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await delete_fn(
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 204)

        conflict_svc = SimpleNamespace(
            delete_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv"))
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 9},
        ):
            with (
                patch.object(
                    crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(),
                            service=conflict_svc,
                        ),
                    )
                self.assertEqual(ex.exception.code, 409)

        delete_tenant_fn = crud_mod.delete_entity_tenant.__wrapped__
        missing_svc = SimpleNamespace(
            delete_with_row_version=AsyncMock(return_value=None)
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 10},
        ):
            with (
                patch.object(
                    crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(),
                            service=missing_svc,
                            tenant_scoped=True,
                        ),
                    )
                self.assertEqual(ex.exception.code, 404)

    async def test_restore_entity_and_restore_entity_tenant_paths(self) -> None:
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        deleted_at = datetime.now(timezone.utc)
        before = SimpleNamespace(id=entity_id, deleted_at=deleted_at)
        restored = SimpleNamespace(id=entity_id, deleted_at=None)
        svc = SimpleNamespace(
            get=AsyncMock(return_value=before),
            update_with_row_version=AsyncMock(return_value=restored),
        )
        registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=svc,
            tenant_scoped=True,
        )
        restore_fn = crud_mod.restore_entity.__wrapped__

        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 11},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await restore_fn(
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry,
                )
        self.assertEqual(status, 204)

        unsupported_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.NONE,
                allow_restore=False,
            ),
            service=svc,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 11},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: unsupported_registry,
                    )
                self.assertEqual(ex.exception.code, 405)

        restore_tenant_fn = crud_mod.restore_entity_tenant.__wrapped__
        before_flag = SimpleNamespace(id=entity_id, is_deleted=True)
        svc_flag = SimpleNamespace(
            get=AsyncMock(return_value=before_flag),
            update_with_row_version=AsyncMock(
                return_value=SimpleNamespace(id=entity_id)
            ),
        )
        registry_flag = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.FLAG,
                soft_delete_column="IsDeleted",
            ),
            service=svc_flag,
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 12},
        ):
            with patch.object(
                crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
            ):
                _, status = await restore_tenant_fn(
                    tenant_id=str(tenant_id),
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: registry_flag,
                )
        self.assertEqual(status, 204)

        conflict_flag = SimpleNamespace(id=entity_id, is_deleted=False)
        svc_conflict = SimpleNamespace(
            get=AsyncMock(return_value=conflict_flag),
            update_with_row_version=AsyncMock(return_value=None),
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 12},
        ):
            with (
                patch.object(
                    crud_mod, "emit_audit_event", new=AsyncMock(return_value=None)
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(
                                soft_delete_mode=SoftDeleteMode.FLAG,
                                soft_delete_column="IsDeleted",
                            ),
                            service=svc_conflict,
                            tenant_scoped=True,
                        ),
                    )
                self.assertEqual(ex.exception.code, 409)

    async def test_create_and_update_validation_error_branches(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        create_tenant_fn = crud_mod.create_entity_tenant.__wrapped__
        create_registry = _FakeRegistry(
            resource=_resource(create_schema=("TenantId", "Name")),
            service=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
            ),
            tenant_scoped=True,
        )

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                "/api/core/acp/v1/tenants/not-a-uuid/Users",
                method="POST",
                json={"Name": "Alice"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_tenant_fn(
                        tenant_id="not-a-uuid",
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: create_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users",
                method="POST",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: create_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users",
                method="POST",
                json={"Name": "Alice", "TenantId": "bad"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: create_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users",
                method="POST",
                json={"Name": "Alice", "TenantId": str(uuid.uuid4())},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: create_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        error_registry = _FakeRegistry(
            resource=_resource(create_schema=("TenantId", "Name")),
            service=SimpleNamespace(
                create=AsyncMock(side_effect=SQLAlchemyError("boom"))
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users",
            method="POST",
            json={"Name": "Alice"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await create_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        update_fn = crud_mod.update_entity.__wrapped__
        update_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                ),
            ),
            tenant_scoped=True,
        )

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="PATCH",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="PATCH",
                json={"DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="PATCH",
                json={"RowVersion": "bad", "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users/not-a-uuid",
                method="PATCH",
                json={"RowVersion": 1, "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        empty_schema_registry = _FakeRegistry(
            resource=_resource(update_schema=None),
            service=SimpleNamespace(),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1},
        ):
            _, status = await update_fn(
                entity_set="Users",
                entity_id=str(entity_id),
                auth_user=str(actor_id),
                logger_provider=_logger,
                registry_provider=lambda: empty_schema_registry,
            )
        self.assertEqual(status, 204)

        sql_error_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: sql_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        update_tenant_fn = crud_mod.update_entity_tenant.__wrapped__
        integrity_error_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(
                    side_effect=IntegrityError(
                        "update",
                        {"display_name": "new"},
                        Exception("duplicate key value violates unique constraint"),
                        None,
                    )
                ),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: integrity_error_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        not_found_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: not_found_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

    async def test_update_delete_and_tenant_delete_error_branches(self) -> None:
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        update_tenant_fn = crud_mod.update_entity_tenant.__wrapped__
        update_registry = _FakeRegistry(
            resource=_resource(update_schema=("TenantId", "DisplayName")),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                ),
            ),
            tenant_scoped=True,
        )

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="PATCH",
                json={"RowVersion": 1, "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(update_schema=("DisplayName",)),
                            service=SimpleNamespace(),
                            tenant_scoped=False,
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/tenants/not-a-uuid/Users/also-bad",
                method="PATCH",
                json={"RowVersion": 1, "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id="not-a-uuid",
                        entity_set="Users",
                        entity_id="also-bad",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="PATCH",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="PATCH",
                json={"DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="PATCH",
                json={"RowVersion": "bad", "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/not-a-uuid",
                method="PATCH",
                json={"RowVersion": 1, "DisplayName": "new"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1},
        ):
            _, status = await update_tenant_fn(
                tenant_id=str(tenant_id),
                entity_set="Users",
                entity_id=str(entity_id),
                auth_user=str(actor_id),
                logger_provider=_logger,
                registry_provider=lambda: _FakeRegistry(
                    resource=_resource(update_schema=None),
                    service=SimpleNamespace(),
                    tenant_scoped=True,
                ),
            )
        self.assertEqual(status, 204)

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": None},
        ):
            _, status = await update_tenant_fn(
                tenant_id=str(tenant_id),
                entity_set="Users",
                entity_id=str(entity_id),
                auth_user=str(actor_id),
                logger_provider=_logger,
                registry_provider=lambda: update_registry,
            )
        self.assertEqual(status, 204)

        conflict_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        sql_error_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: sql_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        not_found_registry = _FakeRegistry(
            resource=_resource(update_schema=("DisplayName",)),
            service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=entity_id)),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="PATCH",
            json={"RowVersion": 1, "DisplayName": "new"},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await update_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: not_found_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

        delete_fn = crud_mod.delete_entity.__wrapped__
        delete_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                )
            ),
            tenant_scoped=True,
        )
        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="DELETE",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="DELETE",
                json={},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}",
                method="DELETE",
                json={"RowVersion": "bad"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users/not-a-uuid",
                method="DELETE",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        delete_sql_error_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom"))
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_sql_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        delete_not_found_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(return_value=None)
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_not_found_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

        delete_tenant_fn = crud_mod.delete_entity_tenant.__wrapped__
        delete_tenant_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                )
            ),
            tenant_scoped=True,
        )
        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="DELETE",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(),
                            service=SimpleNamespace(),
                            tenant_scoped=False,
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/tenants/not-a-uuid/Users/not-a-uuid",
                method="DELETE",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id="not-a-uuid",
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/not-a-uuid",
                method="DELETE",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="DELETE",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="DELETE",
                json={},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
                method="DELETE",
                json={"RowVersion": "bad"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: delete_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        conflict_tenant_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv"))
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: conflict_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        sql_error_tenant_registry = _FakeRegistry(
            resource=_resource(),
            service=SimpleNamespace(
                delete_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom"))
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await delete_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: sql_error_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}",
            method="DELETE",
            json={"RowVersion": 1},
        ):
            with patch.object(
                crud_mod,
                "emit_audit_event",
                new=AsyncMock(return_value=None),
            ):
                _, status = await delete_tenant_fn(
                    tenant_id=str(tenant_id),
                    entity_set="Users",
                    entity_id=str(entity_id),
                    auth_user=str(actor_id),
                    logger_provider=_logger,
                    registry_provider=lambda: delete_tenant_registry,
                )
        self.assertEqual(status, 204)

    async def test_restore_error_branches(self) -> None:
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        restore_fn = crud_mod.restore_entity.__wrapped__
        restore_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                ),
            ),
            tenant_scoped=True,
        )

        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}/$restore",
                method="POST",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}/$restore",
                method="POST",
                json={},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/Users/{entity_id}/$restore",
                method="POST",
                json={"RowVersion": "bad"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users/not-a-uuid/$restore",
                method="POST",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

        weird_registry = _FakeRegistry(
            resource=SimpleNamespace(
                edm_type_name="ACP.User",
                service_key="user_svc",
                namespace="com.test.acp",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode="weird",
                        allow_restore=True,
                        column="DeletedAt",
                    )
                ),
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                ),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: weird_registry,
                    )
                self.assertEqual(ex.exception.code, 405)

        get_error_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(side_effect=SQLAlchemyError("boom")),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: get_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        before_none_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(return_value=None),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: before_none_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

        timestamp_conflict_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=None)
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: timestamp_conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        flag_conflict_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.FLAG,
                soft_delete_column="IsDeleted",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, is_deleted=False)
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: flag_conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        row_conflict_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: row_conflict_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        update_sql_error_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: update_sql_error_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        restored_none_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_fn(
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restored_none_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

        restore_tenant_fn = crud_mod.restore_entity_tenant.__wrapped__
        restore_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id)
                ),
            ),
            tenant_scoped=True,
        )
        with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
                method="POST",
                json=["bad"],
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
                method="POST",
                json={},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
                method="POST",
                json={"RowVersion": "bad"},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/tenants/not-a-uuid/Users/not-a-uuid/$restore",
                method="POST",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id="not-a-uuid",
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/not-a-uuid/$restore",
                method="POST",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id="not-a-uuid",
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restore_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
                method="POST",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(
                                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                                soft_delete_column="DeletedAt",
                            ),
                            service=SimpleNamespace(),
                            tenant_scoped=False,
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
                method="POST",
                json={"RowVersion": 1},
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: _FakeRegistry(
                            resource=_resource(
                                soft_delete_mode=SoftDeleteMode.NONE,
                                allow_restore=False,
                            ),
                            service=SimpleNamespace(),
                            tenant_scoped=True,
                        ),
                    )
                self.assertEqual(ex.exception.code, 405)

        weird_tenant_registry = _FakeRegistry(
            resource=SimpleNamespace(
                edm_type_name="ACP.User",
                service_key="user_svc",
                namespace="com.test.acp",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode="weird",
                        allow_restore=True,
                        column="DeletedAt",
                    )
                ),
                crud=SimpleNamespace(create_schema=None, update_schema=None),
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with patch.object(crud_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: weird_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 405)

        get_error_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(side_effect=SQLAlchemyError("boom")),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: get_error_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        before_none_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(return_value=None),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: before_none_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 404)

        timestamp_conflict_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=None)
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: timestamp_conflict_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        row_conflict_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(side_effect=RowVersionConflict("rv")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: row_conflict_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 409)

        sql_error_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(side_effect=SQLAlchemyError("boom")),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: sql_error_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 500)

        restored_none_tenant_registry = _FakeRegistry(
            resource=_resource(
                soft_delete_mode=SoftDeleteMode.TIMESTAMP,
                soft_delete_column="DeletedAt",
            ),
            service=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(id=entity_id, deleted_at=object())
                ),
                update_with_row_version=AsyncMock(return_value=None),
            ),
            tenant_scoped=True,
        )
        async with self.app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/Users/{entity_id}/$restore",
            method="POST",
            json={"RowVersion": 1},
        ):
            with (
                patch.object(
                    crud_mod,
                    "emit_audit_event",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(crud_mod, "abort", side_effect=_abort_raiser),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await restore_tenant_fn(
                        tenant_id=str(tenant_id),
                        entity_set="Users",
                        entity_id=str(entity_id),
                        auth_user=str(actor_id),
                        logger_provider=_logger,
                        registry_provider=lambda: restored_none_tenant_registry,
                    )
                self.assertEqual(ex.exception.code, 404)
