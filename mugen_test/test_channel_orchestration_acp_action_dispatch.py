"""Integration-style tests for ACP action dispatch with WorkItems actions."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid

from quart import Quart


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
            ),
            get_ext_service=lambda *_: None,
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.action import (  # noqa: E402
    dispatch_entity_action_tenant,
    dispatch_entity_set_action_tenant,
)
from mugen.core.plugin.channel_orchestration.api.validation import (  # noqa: E402
    WorkItemCreateFromChannelValidation,
    WorkItemLinkToCaseValidation,
    WorkItemReplayValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeWorkItemService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_create_from_channel(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "created"}

    async def action_link_to_case(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "linked"}

    async def action_replay(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "replayed"}


class _FakeRegistry:
    def __init__(self, svc: _FakeWorkItemService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="CHANNELORCH.WorkItem",
            service_key="work_item_svc",
            namespace="com.test.channel_orchestration",
            capabilities=SimpleNamespace(
                actions={
                    "create_from_channel": {
                        "schema": WorkItemCreateFromChannelValidation,
                    },
                    "link_to_case": {
                        "schema": WorkItemLinkToCaseValidation,
                    },
                    "replay": {
                        "schema": WorkItemReplayValidation,
                    },
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "WorkItems":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "work_item_svc":
            raise KeyError(service_key)
        return self._svc


class TestChannelOrchestrationAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch for WorkItems actions."""

    async def test_dispatch_create_from_channel_entity_set_action(self) -> None:
        app = Quart("work_items_entity_set_action_dispatch_test")
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeWorkItemService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/WorkItems/"
            "$action/create_from_channel"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"Source": "email", "TraceId": "trace-1"},
        ):
            result = await dispatch_entity_set_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="WorkItems",
                action="create_from_channel",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "created"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], WorkItemCreateFromChannelValidation)
        self.assertEqual(call["data"].source, "email")

    async def test_dispatch_link_to_case_entity_action(self) -> None:
        app = Quart("work_items_entity_action_dispatch_test")
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        linked_case_id = uuid.uuid4()

        fake_service = _FakeWorkItemService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/WorkItems/{entity_id}"
            "/$action/link_to_case"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"RowVersion": 2, "LinkedCaseId": str(linked_case_id)},
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="WorkItems",
                entity_id=str(entity_id),
                action="link_to_case",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "linked"})
        call = fake_service.calls[0]
        self.assertEqual(call["entity_id"], entity_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": entity_id})
        self.assertIsInstance(call["data"], WorkItemLinkToCaseValidation)
        self.assertEqual(call["data"].row_version, 2)
        self.assertEqual(call["data"].linked_case_id, linked_case_id)

    async def test_dispatch_replay_entity_action(self) -> None:
        app = Quart("work_items_replay_action_dispatch_test")
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeWorkItemService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/WorkItems/{entity_id}/$action/replay"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"IncludeMetadata": True},
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="WorkItems",
                entity_id=str(entity_id),
                action="replay",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "replayed"})
        call = fake_service.calls[0]
        self.assertIsInstance(call["data"], WorkItemReplayValidation)
        self.assertTrue(call["data"].include_metadata)
