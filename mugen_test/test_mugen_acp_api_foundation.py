"""Tests for ACP API foundation helper behavior."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock

from quart import Quart
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
from mugen.core.plugin.acp.api import foundation as foundation_mod
from mugen.core.plugin.acp.api.foundation import (
    acquire_idempotency,
    commit_idempotency_failure,
    commit_idempotency_success,
    enforce_schema_bindings,
)
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID


class _FakeRegistry:
    def __init__(self, resources: dict[str, str], services: dict[str, object]) -> None:
        self._resources = resources
        self._services = services

    def get_resource(self, entity_set: str):
        if entity_set not in self._resources:
            raise KeyError(entity_set)
        return SimpleNamespace(service_key=self._resources[entity_set])

    def get_edm_service(self, service_key: str):
        return self._services[service_key]


class TestMugenAcpApiFoundation(unittest.IsolatedAsyncioTestCase):
    """Covers idempotency and schema-binding helper flows."""

    def setUp(self) -> None:
        self.app = Quart("foundation-tests")

    async def test_acquire_idempotency_no_header_noop(self) -> None:
        registry = _FakeRegistry(resources={}, services={})

        async with self.app.test_request_context("/"):
            state = await acquire_idempotency(
                registry=registry,
                tenant_id=None,
                entity_set="Users",
                action_name="provision",
                payload={"Name": "x"},
            )

        self.assertEqual(state, {"enabled": False})

    async def test_acquire_idempotency_replay_response(self) -> None:
        record_id = uuid.uuid4()
        dedup_svc = SimpleNamespace(
            acquire=AsyncMock(
                return_value={
                    "decision": "replay",
                    "record": SimpleNamespace(id=record_id),
                    "response_code": 202,
                    "response_payload": {"Replay": True},
                }
            )
        )
        registry = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": dedup_svc},
        )

        async with self.app.test_request_context(
            "/",
            headers={"X-Idempotency-Key": "abc-123"},
        ):
            state = await acquire_idempotency(
                registry=registry,
                tenant_id=None,
                entity_set="Users",
                action_name=None,
                payload={"Name": "x"},
            )

        response = state["replay_response"]
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["X-Idempotency-Replayed"], "true")
        self.assertEqual(state["record_id"], record_id)

    async def test_acquire_idempotency_acquired_with_scope_fallback(self) -> None:
        record_id = uuid.uuid4()
        dedup_svc = SimpleNamespace(
            acquire=AsyncMock(
                return_value={
                    "decision": "acquired",
                    "record": SimpleNamespace(id=record_id),
                }
            )
        )
        registry = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": dedup_svc},
        )

        async with self.app.test_request_context(
            "/",
            headers={
                "X-Idempotency-Key": "abc-123",
                "X-Idempotency-Scope": "   ",
                "X-Request-Id": "req-1",
            },
        ):
            state = await acquire_idempotency(
                registry=registry,
                tenant_id=None,
                entity_set="Users",
                action_name="provision",
                payload={"Name": "x"},
            )

        self.assertEqual(state["enabled"], True)
        self.assertEqual(state["record_id"], record_id)
        self.assertEqual(
            dedup_svc.acquire.await_args.kwargs["tenant_id"],
            GLOBAL_TENANT_ID,
        )
        self.assertEqual(
            dedup_svc.acquire.await_args.kwargs["scope"],
            "acp:action:Users:provision",
        )

    async def test_acquire_idempotency_with_header_but_missing_service_noop(
        self,
    ) -> None:
        registry = _FakeRegistry(resources={}, services={})

        async with self.app.test_request_context(
            "/",
            headers={"X-Idempotency-Key": "abc-123"},
        ):
            state = await acquire_idempotency(
                registry=registry,
                tenant_id=None,
                entity_set="Users",
                action_name=None,
                payload={"Name": "x"},
            )

        self.assertEqual(state, {"enabled": False})

    async def test_acquire_idempotency_conflict_and_in_progress_abort(self) -> None:
        conflict_svc = SimpleNamespace(
            acquire=AsyncMock(return_value={"decision": "conflict"})
        )
        registry_conflict = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": conflict_svc},
        )

        async with self.app.test_request_context(
            "/",
            headers={"X-Idempotency-Key": "abc-123"},
        ):
            with self.assertRaises(HTTPException) as conflict_error:
                await acquire_idempotency(
                    registry=registry_conflict,
                    tenant_id=None,
                    entity_set="Users",
                    action_name=None,
                    payload={},
                )
        self.assertEqual(conflict_error.exception.code, 409)

        in_progress_svc = SimpleNamespace(
            acquire=AsyncMock(return_value={"decision": "in_progress"})
        )
        registry_in_progress = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": in_progress_svc},
        )
        async with self.app.test_request_context(
            "/",
            headers={"X-Idempotency-Key": "abc-123"},
        ):
            with self.assertRaises(HTTPException) as in_progress_error:
                await acquire_idempotency(
                    registry=registry_in_progress,
                    tenant_id=None,
                    entity_set="Users",
                    action_name=None,
                    payload={},
                )
        self.assertEqual(in_progress_error.exception.code, 409)

    async def test_commit_helpers_call_dedup_service(self) -> None:
        dedup_svc = SimpleNamespace(
            commit_success=AsyncMock(),
            commit_failure=AsyncMock(),
        )
        registry = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": dedup_svc},
        )
        record_id = uuid.uuid4()
        state = {"enabled": True, "record_id": record_id}

        await commit_idempotency_success(
            registry=registry,
            idempotency_state=state,
            response_code=201,
            response_payload={"ok": True},
            result_ref="users/1",
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state=state,
            response_code=500,
            response_payload={"error": "boom"},
            error_code="error",
            error_message="boom",
        )

        dedup_svc.commit_success.assert_awaited_once()
        dedup_svc.commit_failure.assert_awaited_once()

    async def test_commit_helpers_short_circuit_paths(self) -> None:
        dedup_svc = SimpleNamespace(
            commit_success=AsyncMock(),
            commit_failure=AsyncMock(),
        )
        registry = _FakeRegistry(
            resources={"DedupRecords": "dedup"},
            services={"dedup": dedup_svc},
        )

        await commit_idempotency_success(
            registry=registry,
            idempotency_state={"enabled": True, "record_id": None},
            response_code=200,
            response_payload={},
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state={"enabled": True, "record_id": None},
            response_code=500,
            response_payload={},
            error_code=None,
            error_message=None,
        )
        self.assertEqual(dedup_svc.commit_success.await_count, 0)
        self.assertEqual(dedup_svc.commit_failure.await_count, 0)

        missing_registry = _FakeRegistry(resources={}, services={})
        await commit_idempotency_success(
            registry=missing_registry,
            idempotency_state={"enabled": True, "record_id": uuid.uuid4()},
            response_code=200,
            response_payload={},
        )
        await commit_idempotency_failure(
            registry=missing_registry,
            idempotency_state={"enabled": True, "record_id": uuid.uuid4()},
            response_code=500,
            response_payload={},
            error_code=None,
            error_message=None,
        )

    async def test_enforce_schema_bindings_when_enabled(self) -> None:
        schema_svc = SimpleNamespace(
            validate_payload=AsyncMock(
                return_value=(SimpleNamespace(id=uuid.uuid4()), ["invalid payload"])
            )
        )
        binding = SimpleNamespace(schema_definition_id=uuid.uuid4(), is_required=True)
        binding_svc = SimpleNamespace(
            list_active_bindings=AsyncMock(return_value=[binding])
        )
        registry = _FakeRegistry(
            resources={"Schemas": "schemas", "SchemaBindings": "bindings"},
            services={"schemas": schema_svc, "bindings": binding_svc},
        )

        with self.assertRaises(HTTPException) as err:
            await enforce_schema_bindings(
                registry=registry,
                tenant_id=uuid.uuid4(),
                resource_namespace="com.vorsocomputing.mugen.acp",
                entity_set="Users",
                action_name=None,
                payload={"Name": 123},
                binding_kind="create",
                config_provider=lambda: SimpleNamespace(
                    acp=SimpleNamespace(
                        schema_registry=SimpleNamespace(enforce_bindings=True)
                    )
                ),
            )
        self.assertEqual(err.exception.code, 400)

    async def test_enforce_schema_bindings_skips_non_required_failures(self) -> None:
        schema_svc = SimpleNamespace(
            validate_payload=AsyncMock(
                return_value=(SimpleNamespace(id=uuid.uuid4()), ["invalid payload"])
            )
        )
        binding = SimpleNamespace(schema_definition_id=uuid.uuid4(), is_required=False)
        binding_svc = SimpleNamespace(
            list_active_bindings=AsyncMock(return_value=[binding])
        )
        registry = _FakeRegistry(
            resources={"Schemas": "schemas", "SchemaBindings": "bindings"},
            services={"schemas": schema_svc, "bindings": binding_svc},
        )

        await enforce_schema_bindings(
            registry=registry,
            tenant_id=uuid.uuid4(),
            resource_namespace="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name="provision",
            payload={"Name": 123},
            binding_kind="action",
            config_provider=lambda: SimpleNamespace(
                acp=SimpleNamespace(
                    schema_registry=SimpleNamespace(enforce_bindings=True)
                )
            ),
        )

    async def test_enforce_schema_bindings_config_and_registry_short_circuits(
        self,
    ) -> None:
        await enforce_schema_bindings(
            registry=_FakeRegistry(resources={}, services={}),
            tenant_id=uuid.uuid4(),
            resource_namespace="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name=None,
            payload={"Name": "x"},
            binding_kind="create",
            config_provider=lambda: SimpleNamespace(),
        )

        await enforce_schema_bindings(
            registry=_FakeRegistry(resources={}, services={}),
            tenant_id=uuid.uuid4(),
            resource_namespace="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name=None,
            payload={"Name": "x"},
            binding_kind="create",
            config_provider=lambda: SimpleNamespace(acp=SimpleNamespace()),
        )

        await enforce_schema_bindings(
            registry=_FakeRegistry(resources={}, services={}),
            tenant_id=uuid.uuid4(),
            resource_namespace="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name=None,
            payload={"Name": "x"},
            binding_kind="create",
            config_provider=lambda: SimpleNamespace(
                acp=SimpleNamespace(
                    schema_registry=SimpleNamespace(enforce_bindings=True)
                )
            ),
        )

    async def test_enforce_bindings_enabled_returns_false_on_config_provider_error(
        self,
    ) -> None:
        def _boom_provider():
            raise RuntimeError("config unavailable")

        self.assertFalse(
            foundation_mod._enforce_bindings_enabled(  # pylint: disable=protected-access
                config_provider=_boom_provider
            )
        )
