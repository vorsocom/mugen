"""Signal profile authentication and delivery-failure security regressions."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.client.signal import MultiProfileSignalClient
from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.service.context_scope_resolution import ContextScopeResolutionError
from mugen.core.service.ingress_routing import DefaultIngressRoutingService
from mugen.core.utility.client_profile_runtime import get_active_client_profile_id
from mugen_test.test_ingress_binding_security import _Storage
from mugen_test.test_mugen_signal_restapi_ipc_ext import (
    _make_config,
    _new_extension,
    _receive_payload,
    _text_envelope,
)


class TestSignalIngressProfileSecurity(unittest.IsolatedAsyncioTestCase):
    """Use the actual Signal handlers and resolver with conflicting tenant rows."""

    def setUp(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.client_id = uuid.uuid4()
        self.channel_id = uuid.uuid4()
        self.attacker_id = uuid.uuid4()
        binding = {
            "id": uuid.uuid4(),
            "tenant_id": self.tenant_id,
            "channel_profile_id": self.channel_id,
            "channel_key": "signal",
            "identifier_type": "account_number",
            "identifier_value": "+15550000001",
            "is_active": True,
        }
        self.rows = {
            "admin_tenant": [
                {
                    "id": self.tenant_id,
                    "slug": "victim",
                    "status": "active",
                }
            ],
            "admin_messaging_client_profile": [
                {
                    "id": self.client_id,
                    "tenant_id": self.tenant_id,
                    "platform_key": "signal",
                    "profile_key": "victim-signal",
                    "account_number": "+15550000001",
                    "is_active": True,
                }
            ],
            "channel_orchestration_channel_profile": [
                {
                    "id": self.channel_id,
                    "tenant_id": self.tenant_id,
                    "channel_key": "signal",
                    "client_profile_id": self.client_id,
                    "is_active": True,
                }
            ],
            "channel_orchestration_ingress_binding": [
                binding,
                {**binding, "id": uuid.uuid4(), "tenant_id": self.attacker_id},
            ],
        }
        self.storage = _Storage(self.rows)
        self.router = DefaultIngressRoutingService(
            relational_storage_gateway=self.storage,
            logging_gateway=Mock(),
        )
        self.extension = _new_extension(
            config=_make_config(),
            relational_storage_gateway=self.storage,
            ingress_routing_service=self.router,
        )

    def _request(self, *, staged: bool, **changes):
        event = _receive_payload(_text_envelope())
        payload = {
            "client_profile_id": str(self.client_id),
            "account_number": "+15550000001",
            **({"payload": event} if staged else event),
            **changes,
        }
        return IPCCommandRequest(
            platform="signal",
            command="signal_ingress_event" if staged else "signal_restapi_event",
            data=payload,
        )

    async def test_actual_legacy_and_staged_routes_ignore_other_tenant_collision(self):
        observed = []

        async def handle(_envelope, route):
            observed.append((get_active_client_profile_id(), route["tenant_id"]))

        with (
            patch.object(self.extension, "_handle_message_event", new=handle),
            patch.object(
                self.extension, "_is_duplicate_event", new=AsyncMock(return_value=False)
            ),
        ):
            for staged in (False, True):
                await self.extension.process_ipc_command(self._request(staged=staged))
        self.assertEqual(observed, [(self.client_id, str(self.tenant_id))] * 2)
        self.assertTrue(
            all(
                where["tenant_id"] == self.tenant_id
                for where in self.storage.find_many_wheres
            )
        )

    async def test_fresh_failure_cannot_fall_back_to_cached_route(self):
        cached = {
            "client_profile_id": str(self.client_id),
            "tenant_id": str(self.tenant_id),
        }
        for staged in (False, True):
            for changes in (
                {"account_number": "+15559999999"},
                {"client_profile_id": str(uuid.uuid4())},
            ):
                with self.subTest(staged=staged, changes=changes):
                    handler = AsyncMock()
                    with patch.object(
                        self.extension, "_handle_message_event", new=handler
                    ):
                        with self.assertRaises(ContextScopeResolutionError):
                            await self.extension.process_ipc_command(
                                self._request(
                                    staged=staged,
                                    provider_context={"ingress_route": cached},
                                    **changes,
                                )
                            )
                    handler.assert_not_awaited()
        self.assertEqual(len(self.rows["signal_restapi_event_dead_letter"]), 4)

    async def test_missing_identity_and_mismatched_channel_fail_closed(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                with self.assertRaisesRegex(
                    ContextScopeResolutionError, "client_profile_mismatch"
                ):
                    await self.extension.process_ipc_command(
                        self._request(
                            staged=staged,
                            client_profile_id=None,
                            provider_context=7,
                        )
                    )
        self.rows["channel_orchestration_channel_profile"][0][
            "client_profile_id"
        ] = uuid.uuid4()
        with self.assertRaises(ContextScopeResolutionError):
            await self.extension.process_ipc_command(self._request(staged=True))

    async def test_provider_context_profile_is_used_but_cached_route_is_not(self):
        handler = AsyncMock()
        with patch.object(self.extension, "_handle_message_event", new=handler):
            await self.extension.process_ipc_command(
                self._request(
                    staged=True,
                    client_profile_id=None,
                    provider_context={"client_profile_id": str(self.client_id)},
                )
            )
        handler.assert_awaited_once()
        self.extension._config = SimpleNamespace(signal=SimpleNamespace())
        with self.assertRaises(ContextScopeResolutionError):
            await self.extension.process_ipc_command(
                self._request(
                    staged=True,
                    account_number=None,
                    provider_context={
                        "ingress_route": {
                            "client_profile_id": str(self.client_id),
                            "tenant_id": str(self.tenant_id),
                        }
                    },
                )
            )

    async def test_supervisor_overwrites_payload_profile_with_receiving_client(self):
        event = {"client_profile_id": str(self.attacker_id), "params": {"envelope": {}}}

        async def receive_events():
            yield event

        manager = object.__new__(MultiProfileSignalClient)
        manager._event_queue = asyncio.Queue()
        transport = SimpleNamespace(receive_events=receive_events)
        await manager._reader_loop(str(self.client_id), transport)
        delivered = await manager._event_queue.get()
        self.assertEqual(delivered["client_profile_id"], str(self.client_id))
        self.assertEqual(event["client_profile_id"], str(self.attacker_id))
