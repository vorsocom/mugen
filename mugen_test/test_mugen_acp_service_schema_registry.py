"""Tests for schema definition and schema binding services."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException


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


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.service import schema_definition as schema_definition_mod
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.service.schema_binding import SchemaBindingService
from mugen.core.plugin.acp.service.schema_definition import SchemaDefinitionService


class _FakeUnitOfWork:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.updates: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def find(self, _table, filter_groups=None):  # noqa: ANN001
        _ = filter_groups
        return self.rows

    async def update_one(
        self,
        _table,
        where,
        changes,
        returning=False,  # noqa: ANN001
    ):
        _ = returning
        self.updates.append({"where": where, "changes": changes})


class _FakeRsg:
    def __init__(self, rows: list[dict]) -> None:
        self.uow = _FakeUnitOfWork(rows)

    def unit_of_work(self):
        return self.uow


def _build_schema_definition_service(
    max_schema_bytes: int = 1024,
) -> SchemaDefinitionService:
    service = SchemaDefinitionService.__new__(SchemaDefinitionService)
    service._config_provider = lambda: SimpleNamespace(
        acp=SimpleNamespace(
            schema_registry=SimpleNamespace(max_schema_bytes=max_schema_bytes)
        )
    )
    service._rsg = _FakeRsg([])
    service._table = "admin_schema_definition"
    service.get = AsyncMock()
    service.create = AsyncMock()
    service.update_with_row_version = AsyncMock()
    service.list = AsyncMock()
    return service


class TestMugenAcpServiceSchemaRegistry(unittest.IsolatedAsyncioTestCase):
    """Covers schema create/validate/coerce/activate and binding lookup paths."""

    async def test_schema_definition_create_normalizes_checksum(self) -> None:
        service = _build_schema_definition_service()
        super_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))

        with unittest.mock.patch(
            "mugen.core.plugin.acp.service.schema_definition."
            "IRelationalService.create",
            new=super_create,
        ):
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_payload": {"type": "object"},
                },
            )

        self.assertEqual(super_create.await_count, 1)
        payload = super_create.await_args.args[0]
        self.assertIn("checksum_sha256", payload)
        self.assertIn("schema_json", payload)
        self.assertNotIn("schema_payload", payload)

    async def test_schema_definition_create_defaults_missing_tenant_id_to_global(
        self,
    ) -> None:
        service = _build_schema_definition_service()
        super_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))

        with patch.object(
            schema_definition_mod.IRelationalService,
            "create",
            new=super_create,
        ):
            await SchemaDefinitionService.create(
                service,
                {
                    "key": "sample",
                    "version": 1,
                    "schema_payload": {"type": "object"},
                },
            )

        payload = super_create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], GLOBAL_TENANT_ID)

    async def test_schema_definition_create_enforces_size_and_checksum(self) -> None:
        service = _build_schema_definition_service(max_schema_bytes=8)

        with self.assertRaises(HTTPException) as too_large_error:
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_payload": {"very": "large"},
                },
            )
        self.assertEqual(too_large_error.exception.code, 413)

        service = _build_schema_definition_service(max_schema_bytes=1024)
        with self.assertRaises(HTTPException) as checksum_error:
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_payload": {"type": "object"},
                    "checksum_sha256": "bad",
                },
            )
        self.assertEqual(checksum_error.exception.code, 409)

    async def test_validate_and_coerce_payload(self) -> None:
        service = _build_schema_definition_service()
        definition = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            key="sample",
            version=1,
            schema_kind="json_schema",
            schema_json={
                "type": "object",
                "properties": {
                    "Name": {"type": "string", "default": "fallback"},
                },
                "required": ["Name"],
            },
        )
        service.get.return_value = definition

        _, validate_errors = await service.validate_payload(
            tenant_id=definition.tenant_id,
            schema_definition_id=definition.id,
            key=None,
            version=None,
            payload={},
        )
        self.assertEqual(len(validate_errors), 1)

        _, coerced, coerce_errors = await service.coerce_payload(
            tenant_id=definition.tenant_id,
            schema_definition_id=definition.id,
            key=None,
            version=None,
            payload={},
        )
        self.assertEqual(coerce_errors, [])
        self.assertEqual(coerced["Name"], "fallback")

    async def test_activate_version_switches_active_schema(self) -> None:
        tenant_id = uuid.uuid4()
        target_id = uuid.uuid4()
        old_active_id = uuid.uuid4()

        service = _build_schema_definition_service()
        fake_rsg = _FakeRsg(
            rows=[
                {"id": target_id, "status": "draft"},
                {"id": old_active_id, "status": "active"},
                {"id": uuid.uuid4(), "status": "draft"},
            ]
        )
        service._rsg = fake_rsg
        service._table = "admin_schema_definition"
        service.get.return_value = SimpleNamespace(
            id=target_id,
            tenant_id=tenant_id,
            key="sample",
            version=1,
        )

        payload = await service.activate_version(
            tenant_id=tenant_id,
            key="sample",
            version=1,
            activated_by_user_id=uuid.uuid4(),
        )

        self.assertEqual(payload["Status"], "active")
        self.assertEqual(len(fake_rsg.uow.updates), 2)
        self.assertEqual(fake_rsg.uow.updates[0]["where"]["id"], target_id)
        self.assertEqual(fake_rsg.uow.updates[1]["where"]["id"], old_active_id)

    async def test_schema_binding_list_active_bindings(self) -> None:
        service = SchemaBindingService.__new__(SchemaBindingService)
        binding_id = uuid.uuid4()
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(id=binding_id, target_action="provision"),
                SimpleNamespace(id=binding_id, target_action=None),
            ]
        )

        bindings = await service.list_active_bindings(
            tenant_id=uuid.uuid4(),
            target_namespace="com.vorsocomputing.mugen.acp",
            target_entity_set="Users",
            target_action="provision",
            binding_kind="action",
        )

        self.assertEqual(len(bindings), 1)
        self.assertEqual(service.list.await_count, 1)

    def test_schema_definition_provider_and_helper_paths(self) -> None:
        sentinel_config = SimpleNamespace(sample=True)
        with patch.object(
            schema_definition_mod.di,
            "container",
            new=SimpleNamespace(config=sentinel_config),
        ):
            self.assertIs(schema_definition_mod._config_provider(), sentinel_config)

        service = _build_schema_definition_service(max_schema_bytes=-1)
        self.assertGreater(service._max_schema_bytes(), 0)
        service = _build_schema_definition_service(max_schema_bytes="bad")
        self.assertGreater(service._max_schema_bytes(), 0)
        constructed = SchemaDefinitionService(
            table="admin_schema_definition",
            rsg=SimpleNamespace(),
        )
        self.assertEqual(constructed.table, "admin_schema_definition")

        with self.assertRaises(HTTPException) as key_error:
            service._normalize_key("   ")
        self.assertEqual(key_error.exception.code, 400)

        with self.assertRaises(HTTPException) as kind_error:
            service._require_json_schema(
                SimpleNamespace(schema_kind="yaml", schema_json={"type": "object"})
            )
        self.assertEqual(kind_error.exception.code, 400)

        with self.assertRaises(HTTPException) as json_error:
            service._require_json_schema(
                SimpleNamespace(schema_kind="json_schema", schema_json="bad")
            )
        self.assertEqual(json_error.exception.code, 400)

    async def test_schema_definition_create_error_paths(self) -> None:
        service = _build_schema_definition_service(max_schema_bytes=1024)
        with self.assertRaises(HTTPException) as bad_schema:
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_payload": "bad",
                },
            )
        self.assertEqual(bad_schema.exception.code, 400)

        with self.assertRaises(HTTPException) as missing_version:
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "schema_payload": {"type": "object"},
                },
            )
        self.assertEqual(missing_version.exception.code, 400)

        super_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        with patch.object(
            schema_definition_mod.IRelationalService,
            "create",
            new=super_create,
        ):
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_payload": {"type": "object"},
                    "schema_kind": "   ",
                },
            )
        payload = super_create.await_args.args[0]
        self.assertEqual(payload["schema_kind"], "json_schema")
        self.assertEqual(payload["status"], "draft")

        super_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        with patch.object(
            schema_definition_mod.IRelationalService,
            "create",
            new=super_create,
        ):
            await SchemaDefinitionService.create(
                service,
                {
                    "tenant_id": uuid.uuid4(),
                    "key": "sample",
                    "version": 1,
                    "schema_json": {"type": "object"},
                    "status": "active",
                },
            )
        payload = super_create.await_args.args[0]
        self.assertEqual(payload["status"], "active")

    async def test_schema_definition_resolve_and_activate_error_paths(self) -> None:
        service = _build_schema_definition_service()

        with self.assertRaises(HTTPException) as version_required:
            await service.validate_payload(
                tenant_id=uuid.uuid4(),
                schema_definition_id=None,
                key="sample",
                version=None,
                payload={},
            )
        self.assertEqual(version_required.exception.code, 400)

        service.get.return_value = None
        with self.assertRaises(HTTPException) as not_found:
            await service.validate_payload(
                tenant_id=uuid.uuid4(),
                schema_definition_id=uuid.uuid4(),
                key=None,
                version=None,
                payload={},
            )
        self.assertEqual(not_found.exception.code, 404)

        service.get.return_value = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            key="sample",
            version=1,
            schema_kind="json_schema",
            schema_json={"type": "object"},
        )
        _, errors = await service.validate_payload(
            tenant_id=uuid.uuid4(),
            schema_definition_id=None,
            key="sample",
            version=1,
            payload={},
        )
        self.assertEqual(errors, [])

        service.get.return_value = None
        with self.assertRaises(HTTPException) as missing_target:
            await service.activate_version(
                tenant_id=uuid.uuid4(),
                key="sample",
                version=1,
                activated_by_user_id=uuid.uuid4(),
            )
        self.assertEqual(missing_target.exception.code, 404)

        service = _build_schema_definition_service()
        service.get.return_value = SimpleNamespace(id=uuid.uuid4())
        failing_rsg = SimpleNamespace(
            unit_of_work=lambda: _FailingUnitOfWork(),
        )
        service._rsg = failing_rsg
        with self.assertRaises(HTTPException) as activate_error:
            await service.activate_version(
                tenant_id=uuid.uuid4(),
                key="sample",
                version=1,
                activated_by_user_id=uuid.uuid4(),
            )
        self.assertEqual(activate_error.exception.code, 500)

    async def test_schema_definition_action_wrapper_methods(self) -> None:
        service = _build_schema_definition_service()
        definition = SimpleNamespace(id=uuid.uuid4())
        service.validate_payload = AsyncMock(return_value=(definition, []))
        service.coerce_payload = AsyncMock(return_value=(definition, {"Name": "x"}, []))
        service.activate_version = AsyncMock(
            return_value={"Key": "sample", "Version": 1, "Status": "active"}
        )

        payload, status = await service.entity_set_action_validate(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                tenant_id=None,
                schema_definition_id=definition.id,
                key=None,
                version=None,
                payload={"Name": "x"},
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Valid"], True)

        payload, status = await service.action_validate(
            tenant_id=uuid.uuid4(),
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                schema_definition_id=definition.id,
                key=None,
                version=None,
                payload={"Name": "x"},
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Valid"], True)

        payload, status = await service.entity_set_action_coerce(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                tenant_id=None,
                schema_definition_id=definition.id,
                key=None,
                version=None,
                payload={"Name": "x"},
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["CoercedPayload"], {"Name": "x"})

        payload, status = await service.action_coerce(
            tenant_id=uuid.uuid4(),
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                schema_definition_id=definition.id,
                key=None,
                version=None,
                payload={"Name": "x"},
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["CoercedPayload"], {"Name": "x"})

        payload, status = await service.entity_set_action_activate_version(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(tenant_id=None, key="sample", version=1),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Status"], "active")

        payload, status = await service.action_activate_version(
            tenant_id=uuid.uuid4(),
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(key="sample", version=1),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Status"], "active")

    async def test_schema_binding_list_paths_and_constructor(self) -> None:
        service = SchemaBindingService(
            table="admin_schema_binding", rsg=SimpleNamespace()
        )
        binding_id = uuid.uuid4()
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(id=None, target_action=None),
                SimpleNamespace(id=binding_id, target_action=None),
            ]
        )

        bindings = await service.list_active_bindings(
            tenant_id=uuid.uuid4(),
            target_namespace="com.vorsocomputing.mugen.acp",
            target_entity_set="Users",
            target_action=None,
            binding_kind="create",
        )
        self.assertEqual(len(bindings), 1)


class _FailingUnitOfWork:
    async def __aenter__(self):
        raise SQLAlchemyError("db")

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False
