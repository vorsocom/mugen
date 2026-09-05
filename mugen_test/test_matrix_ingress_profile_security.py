"""Matrix routing must retain the identity of its authenticated client."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import uuid

from mugen.core.client.matrix import DefaultMatrixClient
from mugen.core.service.ingress_routing import DefaultIngressRoutingService
from mugen.core.utility.client_profile_runtime import client_profile_scope
from mugen_test.test_mugen_service_ingress_routing import _FakeRsg


class TestMatrixIngressProfileSecurity(unittest.IsolatedAsyncioTestCase):
    """Use actual Matrix route resolution against colliding tenant bindings."""

    def setUp(self) -> None:
        self.tenant = uuid.uuid4()
        self.other_tenant = uuid.uuid4()
        self.profile = uuid.uuid4()
        self.channel = uuid.uuid4()
        self.binding = uuid.uuid4()
        self.recipient = "@assistant:example.com"
        self.rows = {
            "admin_tenant": [
                {"id": self.tenant, "slug": "owner", "status": "active"},
                {"id": self.other_tenant, "slug": "other", "status": "active"},
            ],
            "admin_messaging_client_profile": [
                {
                    "id": self.profile,
                    "tenant_id": self.tenant,
                    "platform_key": "matrix",
                    "profile_key": "owner-matrix",
                    "recipient_user_id": self.recipient,
                    "is_active": True,
                }
            ],
            "channel_orchestration_channel_profile": [
                {
                    "id": self.channel,
                    "tenant_id": self.tenant,
                    "client_profile_id": self.profile,
                    "is_active": True,
                }
            ],
            "channel_orchestration_ingress_binding": [
                {
                    "id": self.binding,
                    "tenant_id": self.tenant,
                    "channel_key": "matrix",
                    "identifier_type": "recipient_user_id",
                    "identifier_value": self.recipient,
                    "channel_profile_id": self.channel,
                    "is_active": True,
                }
            ],
        }
        self.storage = _FakeRsg(self.rows)
        self.logger = Mock()
        self.client = object.__new__(DefaultMatrixClient)
        self.client._config = SimpleNamespace(
            matrix=SimpleNamespace(client_profile_id=str(self.profile))
        )
        self.client._vendor_client = SimpleNamespace(user_id=self.recipient)
        self.client._logging_gateway = self.logger
        self.client._ingress_routing_service = DefaultIngressRoutingService(
            relational_storage_gateway=self.storage,
            logging_gateway=self.logger,
        )

    async def _resolve(self):
        return await self.client._resolve_message_ingress(
            room=SimpleNamespace(room_id="!room:example.com"),
            message=SimpleNamespace(sender="@sender:example.com"),
        )

    async def test_legacy_collision_cannot_change_the_client_tenant(self) -> None:
        self.rows["channel_orchestration_ingress_binding"].append(
            {
                **self.rows["channel_orchestration_ingress_binding"][0],
                "id": uuid.uuid4(),
                "tenant_id": self.other_tenant,
            }
        )
        # An unrelated task-local profile must not override the Matrix session.
        with client_profile_scope(uuid.uuid4()):
            scope, metadata = await self._resolve()
        self.assertEqual(scope.tenant_id, str(self.tenant))
        route = metadata["ingress_route"]
        self.assertEqual(route["client_profile_id"], str(self.profile))
        self.assertEqual(route["binding_id"], str(self.binding))
        self.assertTrue(self.storage.find_many_wheres)
        self.assertTrue(
            all(
                where["tenant_id"] == self.tenant
                for where in self.storage.find_many_wheres
            )
        )

    async def test_recipient_mismatch_fails_before_binding_lookup(self) -> None:
        self.client._vendor_client.user_id = "@another:example.com"
        self.assertIsNone(await self._resolve())
        self.assertFalse(self.storage.find_many_wheres)
        self.assertEqual(
            self.client._matrix_metrics[
                "matrix.routing.dropped.client_profile_mismatch"
            ],
            1,
        )
        self.logger.warning.assert_called_once()

    async def test_channel_cannot_select_a_different_client_profile(self) -> None:
        self.rows["channel_orchestration_channel_profile"][0][
            "client_profile_id"
        ] = uuid.uuid4()
        self.assertIsNone(await self._resolve())
        self.assertEqual(
            self.client._matrix_metrics[
                "matrix.routing.dropped.client_profile_mismatch"
            ],
            1,
        )

    async def test_missing_client_identity_cannot_fall_back_to_global_lookup(
        self,
    ) -> None:
        self.client._config.matrix.client_profile_id = None
        self.assertIsNone(await self._resolve())
        self.assertFalse(self.storage.find_many_wheres)
        self.assertEqual(
            self.client._matrix_metrics["matrix.routing.dropped.resolution_error"],
            1,
        )
