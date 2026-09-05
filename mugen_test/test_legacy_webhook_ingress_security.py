"""Authenticate legacy messaging webhooks before tenant-scoped IPC routing."""

import base64
import hashlib
import hmac
from importlib import import_module
from inspect import unwrap
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from quart import Quart
from werkzeug.exceptions import InternalServerError

from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.service.ingress_routing import DefaultIngressRoutingService
from mugen.core.service.ipc import DefaultIPCService
from mugen.core.utility.client_profile_runtime import (
    client_profile_scope,
    get_active_client_profile_id,
)
from mugen_test.test_ingress_binding_security import _Storage

_TRANSPORTS = {
    "line": (
        "line.messagingapi",
        "line_messagingapi_webhook_event",
        "line_webhook_signature_required",
        "_process_single_event",
    ),
    "telegram": (
        "telegram.botapi",
        "telegram_botapi_webhook_event",
        "telegram_webhook_secret_required",
        "_handle_message_update",
    ),
    "wechat": (
        "wechat",
        "wechat_official_account_event",
        "wechat_provider_required",
        "_process_inbound_message",
    ),
}


class TestLegacyWebhookIngressSecurity(unittest.IsolatedAsyncioTestCase):
    """Retain authenticated identity through real API, IPC, and route resolution."""

    async def _exercise(
        self, platform: str, *, failure: str | None = None, staged: bool = False
    ) -> None:
        package, endpoint_name, decorator_name, processor_name = _TRANSPORTS[platform]
        fixtures = import_module(
            f"mugen_test.test_mugen_{package.replace('.', '_')}_ipc_ext"
        )
        webhook = import_module(f"mugen.core.plugin.{package}.api.webhook")
        decorators = import_module(f"mugen.core.plugin.{package}.api.decorator")
        tenant, attacker, client, channel, binding = (uuid.uuid4() for _ in range(5))
        rows = {
            "admin_tenant": [
                {"id": tenant, "slug": "victim", "status": "active"},
                {"id": attacker, "slug": "attacker", "status": "active"},
            ],
            "admin_messaging_client_profile": [
                {
                    "id": client,
                    "tenant_id": tenant,
                    "platform_key": platform,
                    "profile_key": "victim-client",
                    "path_token": "victim-path",
                    "is_active": True,
                }
            ],
            "channel_orchestration_channel_profile": [
                {
                    "id": channel,
                    "tenant_id": tenant,
                    "channel_key": platform,
                    "client_profile_id": client,
                    "is_active": True,
                }
            ],
            "channel_orchestration_ingress_binding": [
                {
                    "id": binding,
                    "tenant_id": tenant,
                    "channel_key": platform,
                    "channel_profile_id": channel,
                    "identifier_type": "path_token",
                    "identifier_value": "victim-path",
                    "is_active": True,
                }
            ],
        }
        bindings = rows["channel_orchestration_ingress_binding"]
        bindings.append({**bindings[0], "id": uuid.uuid4(), "tenant_id": attacker})
        if failure == "missing_binding":
            bindings[:] = [bindings[1]]
        elif failure == "client_mismatch":
            rows["channel_orchestration_channel_profile"][0][
                "client_profile_id"
            ] = uuid.uuid4()

        storage = _Storage(rows)
        logger = Mock()
        router = DefaultIngressRoutingService(
            relational_storage_gateway=storage,
            logging_gateway=logger,
        )
        extension = fixtures._new_extension(
            config=fixtures._make_config(),
            relational_storage_gateway=storage,
            ingress_routing_service=router,
        )
        ipc = DefaultIPCService(logging_gateway=logger)
        ipc.bind_ipc_extension(extension)
        if staged:
            await self._exercise_staged(
                platform=platform,
                failure=failure,
                fixtures=fixtures,
                extension=extension,
                processor_name=processor_name,
                ipc=ipc,
                storage=storage,
                rows=rows,
                tenant=tenant,
                attacker=attacker,
                client=client,
                binding=binding,
            )
            return
        requests, results, processed = [], [], []

        async def dispatch(request):
            requests.append(request)
            # IPC may cross a queue boundary; only the envelope survives that hop.
            with client_profile_scope(None):
                result = await ipc.handle_ipc_request(request)
            results.append(result)
            return result

        async def process(*args, **kwargs):
            route = kwargs.get("ingress_route") or args[-1]
            processed.append((get_active_client_profile_id(), route))

        ipc_endpoint = SimpleNamespace(handle_ipc_request=dispatch)
        runtime = SimpleNamespace(
            **{
                platform: SimpleNamespace(
                    channel=SimpleNamespace(secret="secret"),
                    webhook=SimpleNamespace(
                        secret_token="secret",
                        signature_token="secret",
                        aes_enabled=False,
                    ),
                    provider="official_account",
                )
            }
        )
        profile_service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=SimpleNamespace(id=client)
            ),
            build_runtime_config=AsyncMock(return_value=runtime),
        )
        endpoint = unwrap(getattr(webhook, endpoint_name))

        async def invoke(**kwargs):
            if platform == "wechat":
                kwargs.update(
                    config_provider=lambda: runtime,
                    client_profile_service_provider=lambda: profile_service,
                )
            return await endpoint(
                **kwargs,
                ipc_provider=lambda: ipc_endpoint,
                logger_provider=lambda: logger,
            )

        authenticate = getattr(decorators, decorator_name)
        if platform == "wechat":
            wrapped = authenticate(
                "official_account",
                config_provider=lambda: runtime,
                logger_provider=lambda: logger,
            )(invoke)
            body = (
                b"<xml><FromUserName>sender</FromUserName><MsgId>message-1</MsgId>"
                b"<MsgType>text</MsgType><Content>hello</Content></xml>"
            )
            signature = hashlib.sha1(b"12secret").hexdigest()
            query = f"?timestamp=1&nonce=2&signature={signature}"
        else:
            wrapped = authenticate(
                invoke,
                config_provider=lambda: runtime,
                logger_provider=lambda: logger,
            )
            payload = (
                {"events": [fixtures._message_event()]}
                if platform == "line"
                else fixtures._make_private_text_message_update()
            )
            body = json.dumps(payload).encode()
            query = ""
        headers = {
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": "secret",
            "X-Line-Signature": base64.b64encode(
                hmac.new(b"secret", body, hashlib.sha256).digest()
            ).decode(),
        }
        app = Quart(f"legacy-{platform}-ingress-security")
        with (
            patch.object(
                decorators, "_client_profile_service", return_value=profile_service
            ),
            patch.object(extension, processor_name, new=process),
        ):
            async with app.test_request_context(
                "/webhook/victim-path" + query,
                method="POST",
                data=body,
                headers=headers,
            ):
                if failure is None:
                    response = await wrapped(path_token="victim-path")
                    self.assertEqual(
                        response,
                        "success" if platform == "wechat" else {"response": "OK"},
                    )
                else:
                    with self.assertRaises(InternalServerError):
                        await wrapped(path_token="victim-path")

        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].data["authenticated_client_profile_id"], str(client)
        )
        self.assertEqual(len(results), 1)
        if failure is None:
            self.assertFalse(results[0].errors)
            self.assertEqual(len(processed), 1)
            active_client, route = processed[0]
            self.assertEqual(active_client, client)
            self.assertEqual(route["tenant_id"], str(tenant))
            self.assertEqual(route["binding_id"], str(binding))
        else:
            self.assertTrue(results[0].errors)
            self.assertFalse(processed)
            dead_letters = rows[extension._event_dead_letter_table]
            self.assertEqual(len(dead_letters), 1)
            self.assertEqual(dead_letters[0]["reason_code"], "route_unresolved")
        self.assertTrue(storage.find_many_wheres)
        self.assertTrue(
            all(where["tenant_id"] == tenant for where in storage.find_many_wheres)
        )
        self.assertIsNone(get_active_client_profile_id())

    async def test_authenticated_ipc_survives_cross_tenant_collision(self) -> None:
        for platform in _TRANSPORTS:
            with self.subTest(platform=platform):
                await self._exercise(platform)

    async def test_missing_owner_binding_returns_http_500(self) -> None:
        for platform in _TRANSPORTS:
            with self.subTest(platform=platform):
                await self._exercise(platform, failure="missing_binding")

    async def test_mismatched_channel_client_returns_http_500(self) -> None:
        for platform in _TRANSPORTS:
            with self.subTest(platform=platform):
                await self._exercise(platform, failure="client_mismatch")

    async def _exercise_staged(
        self,
        *,
        platform,
        failure,
        fixtures,
        extension,
        processor_name,
        ipc,
        storage,
        rows,
        tenant,
        attacker,
        client,
        binding,
    ) -> None:
        # Legacy metadata has a stale tenant but lacks a resolved client profile.
        provider_context = {
            "path_token": "victim-path",
            "provider": "official_account",
            "ingress_route": {"tenant_id": str(attacker)},
        }
        if platform == "line":
            event = fixtures._message_event()
        elif platform == "telegram":
            event = fixtures._make_private_text_message_update()
        else:
            event = fixtures._make_text_payload()
        data = {
            "client_profile_id": str(client),
            "payload": event,
            "provider_context": provider_context,
        }
        if failure == "missing_profile":
            data.pop("client_profile_id")
            provider_context["ingress_route"]["client_profile_id"] = str(client)
        elif failure == "cached_mismatch":
            provider_context["ingress_route"]["client_profile_id"] = str(uuid.uuid4())
        elif failure == "missing_cached_client":
            provider_context.pop("path_token")

        processed = []

        async def process(*args, **kwargs):
            route = kwargs.get("ingress_route") or args[-1]
            processed.append((get_active_client_profile_id(), route))

        with (
            patch.object(extension, processor_name, new=process),
            client_profile_scope(None),
        ):
            result = await ipc.handle_ipc_request(
                IPCCommandRequest(
                    platform=platform,
                    command=f"{platform}_ingress_event",
                    data=data,
                )
            )
        if failure is None:
            self.assertFalse(result.errors)
            self.assertEqual(len(processed), 1)
            active_client, route = processed[0]
            self.assertEqual(active_client, client)
            self.assertEqual(route["tenant_id"], str(tenant))
            self.assertEqual(route["client_profile_id"], str(client))
            self.assertEqual(route["binding_id"], str(binding))
        else:
            self.assertEqual(len(result.errors), 1)
            self.assertFalse(processed)
            expected_reason = (
                "route_unresolved"
                if failure in {"missing_binding", "client_mismatch"}
                else "client_profile_mismatch"
            )
            self.assertIn(expected_reason, result.errors[0].error)
        if failure in {"missing_profile", "cached_mismatch", "missing_cached_client"}:
            self.assertFalse(storage.find_many_wheres)
        else:
            self.assertTrue(storage.find_many_wheres)
            self.assertTrue(
                all(where["tenant_id"] == tenant for where in storage.find_many_wheres)
            )
            if failure is not None:
                dead_letters = rows[extension._event_dead_letter_table]
                self.assertEqual(len(dead_letters), 1)
                self.assertEqual(dead_letters[0]["reason_code"], "route_unresolved")
        self.assertIsNone(get_active_client_profile_id())

    async def test_staged_replay_resolves_only_its_receiving_client(self) -> None:
        for platform in _TRANSPORTS:
            with self.subTest(platform=platform):
                await self._exercise(platform, staged=True)

    async def test_staged_replay_rejects_failed_lookup_without_stale_fallback(
        self,
    ) -> None:
        for platform in _TRANSPORTS:
            for failure in ("missing_binding", "client_mismatch"):
                with self.subTest(platform=platform, failure=failure):
                    await self._exercise(platform, failure=failure, staged=True)

    async def test_staged_replay_requires_matching_canonical_and_cached_client(
        self,
    ) -> None:
        for platform in _TRANSPORTS:
            for failure in (
                "missing_profile",
                "cached_mismatch",
                "missing_cached_client",
            ):
                with self.subTest(platform=platform, failure=failure):
                    await self._exercise(platform, failure=failure, staged=True)
