"""Security regressions for tenant-owned ingress bindings and authenticated routing."""

import base64
from dataclasses import replace
import hashlib
import hmac
from importlib import import_module
from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from werkzeug.exceptions import BadRequest, InternalServerError

from mugen.core.contract.service.ingress_routing import IngressRouteRequest
from mugen.core.plugin.channel_orchestration.service.ingress_binding import (
    IngressBindingService,
)
from mugen.core.plugin.whatsapp.wacapi.api.webhook import (
    WhatsAppWebhookContext,
    whatsapp_wacapi_event,
)
from mugen.core.service.ingress_routing import DefaultIngressRoutingService
from mugen.core.service.context_scope_resolution import ContextScopeResolutionError
from mugen.core.service.messaging_ingress_extractors import (
    extract_whatsapp_stage_entries,
)
from mugen_test.test_mugen_service_ingress_routing import _FakeRsg
from mugen.core.utility.client_profile_runtime import client_profile_scope


class _Storage(_FakeRsg):
    """Use actual service writes with a deterministic tenant-aware read store."""

    async def insert_one(self, table, values):
        row = {"id": uuid.uuid4(), "is_active": True, "row_version": 1, **values}
        self._rows.setdefault(table, []).append(row)
        return dict(row)

    async def update_one(self, table, where, changes, **_kwargs):
        for row in self._rows.get(table, []):
            if all(row.get(key) == value for key, value in where.items()):
                row.update(changes)
                return dict(row)
        return None


class TestIngressBindingSecurity(unittest.IsolatedAsyncioTestCase):
    """Exercise ownership checks and delivery outcomes using the actual resolver."""

    def setUp(self) -> None:
        self.tenant = uuid.uuid4()
        self.attacker = uuid.uuid4()
        self.channel = uuid.uuid4()
        self.client = uuid.uuid4()
        self.rows = {
            "admin_tenant": [
                {"id": self.tenant, "slug": "victim", "status": "active"},
                {"id": self.attacker, "slug": "attacker", "status": "active"},
            ],
            "admin_messaging_client_profile": [
                {
                    "id": self.client,
                    "tenant_id": self.tenant,
                    "platform_key": "whatsapp",
                    "profile_key": "victim-client",
                    "phone_number_id": "victim-phone",
                    "path_token": "victim-path",
                    "is_active": True,
                }
            ],
            "channel_orchestration_channel_profile": [
                {
                    "id": self.channel,
                    "tenant_id": self.tenant,
                    "channel_key": "whatsapp",
                    "client_profile_id": self.client,
                    "is_active": True,
                }
            ],
            "channel_orchestration_ingress_binding": [],
        }
        self.rsg = _Storage(self.rows)
        self.service = IngressBindingService(
            "channel_orchestration_ingress_binding", self.rsg
        )
        self.values = {
            "tenant_id": self.tenant,
            "channel_profile_id": self.channel,
            "channel_key": "whatsapp",
            "identifier_type": "phone_number_id",
            "identifier_value": "victim-phone",
        }
        self.router = DefaultIngressRoutingService(
            relational_storage_gateway=self.rsg, logging_gateway=Mock()
        )
        self.request = IngressRouteRequest(
            platform="whatsapp",
            channel_key="whatsapp",
            identifier_type="phone_number_id",
            identifier_value="victim-phone",
            authenticated_client_profile_id=self.client,
        )

    async def test_create_rejects_tenant_and_client_identifier_theft(self) -> None:
        for changes in (
            {"tenant_id": self.attacker},
            {"channel_profile_id": None},
            {"channel_profile_id": uuid.uuid4()},
            {"identifier_value": "somebody-elses-phone"},
            {"identifier_type": "unverified-identifier"},
            {"identifier_value": " "},
        ):
            with self.subTest(changes=changes), self.assertRaises(BadRequest):
                await self.service.create({**self.values, **changes})
        self.assertEqual(self.rows[self.service.table], [])
        created = await self.service.create(self.values)
        self.assertEqual(created.tenant_id, self.tenant)

        profile = self.rows["channel_orchestration_channel_profile"][0]
        profile["client_profile_id"] = uuid.uuid4()
        with self.assertRaises(BadRequest):
            await self.service.create(self.values)

    async def test_custom_channel_profile_still_requires_tenant_ownership(self) -> None:
        values = {**self.values, "channel_key": "custom"}
        with self.assertRaises(BadRequest):
            await self.service.create(values)
        self.rows["channel_orchestration_channel_profile"][0]["channel_key"] = "custom"
        self.assertIsNotNone(await self.service.create(values))
        values["channel_profile_id"] = None
        self.assertIsNotNone(await self.service.create(values))

    async def test_update_and_reactivation_revalidate_persisted_ownership(self) -> None:
        created = await self.service.create(self.values)
        where = {"id": created.id, "tenant_id": self.tenant}
        for versioned in (False, True):

            async def update(changes):
                if versioned:
                    return await self.service.update_with_row_version(
                        where, expected_row_version=1, changes=changes
                    )
                return await self.service.update(where, changes)

            for changes in (
                {"identifier_value": "stolen"},
                {"tenant_id": self.attacker},
                {"channel_profile_id": None},
            ):
                with self.subTest(versioned=versioned, changes=changes):
                    with self.assertRaises(BadRequest):
                        await update(changes)
            self.assertIsNotNone(await update({"is_active": False}))
            self.rows["admin_messaging_client_profile"][0]["is_active"] = False
            with self.assertRaises(BadRequest):
                await update({"is_active": True})
            self.assertIsNotNone(await update({"is_active": False}))
            self.rows["admin_messaging_client_profile"][0]["is_active"] = True
            self.assertIsNotNone(await update({"is_active": True}))
        missing = {"id": uuid.uuid4()}
        self.assertIsNone(await self.service.update(missing, {"is_active": True}))
        self.assertIsNone(
            await self.service.update_with_row_version(
                missing, expected_row_version=1, changes={"is_active": True}
            )
        )

    async def test_authenticated_routing_survives_legacy_cross_tenant_collision(self):
        victim = await self.service.create(self.values)
        self.rows[self.service.table].append(
            {
                **self.values,
                "id": uuid.uuid4(),
                "tenant_id": self.attacker,
                "is_active": True,
            }
        )
        with client_profile_scope(self.client):
            resolved = await self.router.resolve(
                replace(self.request, authenticated_client_profile_id=None)
            )
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.result.tenant_id, self.tenant)
        self.assertEqual(resolved.result.binding_id, victim.id)
        self.assertEqual(resolved.result.client_profile_id, self.client)
        self.assertTrue(
            all(
                where["tenant_id"] == self.tenant for where in self.rsg.find_many_wheres
            )
        )

    async def test_authenticated_routing_rejects_profile_and_tenant_mismatch(self):
        await self.service.create(self.values)
        for changes, expected in (
            (
                {"authenticated_client_profile_id": uuid.uuid4()},
                "client_profile_mismatch",
            ),
            ({"identifier_value": "wrong-phone"}, "client_profile_mismatch"),
            ({"identifier_type": "unsafe-field"}, "client_profile_mismatch"),
            ({"tenant_slug": "attacker"}, "unauthorized_tenant"),
        ):
            with self.subTest(changes=changes):
                resolved = await self.router.resolve(replace(self.request, **changes))
                self.assertFalse(resolved.ok)
                self.assertEqual(resolved.reason_code, expected)
        self.rows["admin_messaging_client_profile"][0]["tenant_id"] = "invalid"
        resolved = await self.router.resolve(self.request)
        self.assertEqual(resolved.reason_code, "unauthorized_tenant")
        self.rows["admin_messaging_client_profile"][0]["tenant_id"] = self.tenant
        self.rows["channel_orchestration_channel_profile"][0][
            "client_profile_id"
        ] = uuid.uuid4()
        resolved = await self.router.resolve(self.request)
        self.assertEqual(resolved.reason_code, "client_profile_mismatch")

    def _payload(self):
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "victim-phone"},
                                "messages": [{"id": "wamid-victim", "from": "sender"}],
                            },
                        }
                    ]
                }
            ]
        }

    async def test_authenticated_whatsapp_extraction_and_http_delivery_failure(self):
        await self.service.create(self.values)
        entries = await extract_whatsapp_stage_entries(
            path_token="victim-path",
            payload=self._payload(),
            relational_storage_gateway=self.rsg,
            logging_gateway=Mock(),
            authenticated_client_profile_id=self.client,
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event.client_profile_id, self.client)
        self.assertEqual(
            entries[0].event.provider_context["ingress_route"]["tenant_id"],
            str(self.tenant),
        )
        # A real extraction failure must surface as a retryable HTTP error and
        # must never reach stage([]), which would silently acknowledge delivery.
        self.rows[self.service.table].clear()
        stage = AsyncMock()
        with self.assertRaises(InternalServerError):
            await unwrap(whatsapp_wacapi_event)(
                path_token="victim-path",
                ingress_provider=lambda: SimpleNamespace(stage=stage),
                relational_storage_gateway_provider=lambda: self.rsg,
                logger_provider=lambda: Mock(),
                change_registry_provider=lambda: None,
                whatsapp_webhook_context=WhatsAppWebhookContext(
                    request_id="security-test",
                    payload_fingerprint="test",
                    client_profile_id=str(self.client),
                    message_change_count=1,
                    filtered_payload=self._payload(),
                ),
            )
        stage.assert_not_awaited()

    async def test_authenticated_webhook_scope_reaches_actual_route_lookup(self):
        from mugen.core.service import messaging_ingress_extractors as extractors

        for platform, package, decorator_name, payload in (
            (
                "line",
                "line.messagingapi",
                "line_webhook_signature_required",
                {"events": [{"type": "message", "message": {"id": "line-1"}}]},
            ),
            (
                "telegram",
                "telegram.botapi",
                "telegram_webhook_secret_required",
                {"update_id": 1, "message": {"text": "hello"}},
            ),
            (
                "wechat",
                "wechat",
                "wechat_provider_required",
                {"MsgId": "wechat-1", "FromUserName": "sender"},
            ),
        ):
            with self.subTest(platform=platform):
                self.rows[self.service.table].clear()
                profile = self.rows["admin_messaging_client_profile"][0]
                profile["platform_key"] = platform
                self.rows["channel_orchestration_channel_profile"][0][
                    "channel_key"
                ] = platform
                values = {
                    **self.values,
                    "channel_key": platform,
                    "identifier_type": "path_token",
                    "identifier_value": "victim-path",
                }
                await self.service.create(values)
                self.rows[self.service.table].append(
                    {**values, "tenant_id": self.attacker, "is_active": True}
                )
                module = import_module(f"mugen.core.plugin.{package}.api.decorator")
                runtime = SimpleNamespace(
                    **{
                        platform: SimpleNamespace(
                            channel=SimpleNamespace(secret="secret"),
                            webhook=SimpleNamespace(secret_token="secret"),
                            provider="official_account",
                        )
                    }
                )
                service = SimpleNamespace(
                    resolve_active_by_identifier=AsyncMock(
                        return_value=SimpleNamespace(id=self.client)
                    ),
                    build_runtime_config=AsyncMock(return_value=runtime),
                )
                raw_body = b"authenticated-body"
                headers = {
                    "X-Telegram-Bot-Api-Secret-Token": "secret",
                    "X-Line-Signature": base64.b64encode(
                        hmac.new(b"secret", raw_body, hashlib.sha256).digest()
                    ).decode(),
                }
                request = SimpleNamespace(
                    headers=headers, get_data=AsyncMock(return_value=raw_body)
                )

                async def endpoint(**_kwargs):
                    kwargs = {
                        "path_token": "victim-path",
                        "payload": payload,
                        "relational_storage_gateway": self.rsg,
                        "logging_gateway": Mock(),
                    }
                    if platform == "wechat":
                        kwargs["provider"] = "official_account"
                    return await getattr(
                        extractors, f"extract_{platform}_stage_entries"
                    )(**kwargs)

                decorator = getattr(module, decorator_name)
                if platform == "wechat":
                    wrapped = decorator(
                        "official_account",
                        config_provider=lambda: None,
                        logger_provider=lambda: Mock(),
                    )(endpoint)
                else:
                    wrapped = decorator(
                        endpoint,
                        config_provider=lambda: None,
                        logger_provider=lambda: Mock(),
                    )
                with patch.object(
                    module, "_client_profile_service", return_value=service
                ), patch.object(module, "request", request, create=True):
                    entries = await wrapped(path_token="victim-path")
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].event.client_profile_id, self.client)
                self.assertEqual(
                    entries[0].event.provider_context["ingress_route"]["tenant_id"],
                    str(self.tenant),
                )
                self.rows[self.service.table].clear()
                with client_profile_scope(self.client):
                    with self.assertRaisesRegex(
                        ContextScopeResolutionError, "route_unresolved"
                    ):
                        await endpoint()

    async def test_legacy_whatsapp_ipc_preserves_authenticated_profile(self):
        from mugen.core.contract.service.ipc import IPCCommandRequest
        from mugen_test.test_mugen_whatsapp_wacapi_ipc_ext import (
            _make_config,
            _new_extension,
        )
        from mugen.core.utility.client_profile_runtime import (
            get_active_client_profile_id,
        )

        await self.service.create(self.values)
        extension = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=self.rsg,
            ingress_routing_service=self.router,
        )
        processed_profiles = []

        async def process(_value, _message):
            processed_profiles.append(get_active_client_profile_id())

        with patch.object(extension, "_process_message_event", new=process):
            await extension._wacapi_event(  # pylint: disable=protected-access
                IPCCommandRequest(
                    platform="whatsapp",
                    command="whatsapp_wacapi_event",
                    data={
                        "payload": self._payload(),
                        "authenticated_client_profile_id": str(self.client),
                    },
                )
            )
        self.assertEqual(processed_profiles, [self.client])

    async def test_whatsapp_replay_keeps_canonical_client_scope(self):
        from mugen.core.contract.service.ipc import IPCCommandRequest
        from mugen_test.test_mugen_whatsapp_wacapi_ipc_ext import (
            _make_config,
            _new_extension,
        )

        await self.service.create(self.values)
        self.rows[self.service.table].append(
            {**self.values, "tenant_id": self.attacker, "is_active": True}
        )
        extension = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=self.rsg,
            ingress_routing_service=self.router,
        )
        event = {"event_value": {}, "message": {"id": "replay-victim"}}
        provider = {"phone_number_id": "victim-phone", "ingress_route": {}}

        def request(client_profile_id, provider_context):
            return IPCCommandRequest(
                platform="whatsapp",
                command="whatsapp_ingress_event",
                data={
                    "client_profile_id": client_profile_id,
                    "payload": event,
                    "provider_context": provider_context,
                },
            )

        process = AsyncMock()
        with patch.object(extension, "_process_message_event", new=process):
            await extension.process_ipc_command(request(str(self.client), provider))
            route = process.await_args.args[2]
            self.assertEqual(route["tenant_id"], str(self.tenant))
            self.assertEqual(route["client_profile_id"], str(self.client))
            process.reset_mock()
            for client_profile_id, context in (
                (None, provider),
                (str(self.client), {**provider, "phone_number_id": "wrong-phone"}),
                (
                    str(self.client),
                    {
                        **provider,
                        "ingress_route": {
                            "client_profile_id": str(uuid.uuid4()),
                            "tenant_id": str(self.attacker),
                        },
                    },
                ),
                (str(self.client), {"ingress_route": {}}),
            ):
                with self.assertRaises(ContextScopeResolutionError):
                    await extension.process_ipc_command(
                        request(client_profile_id, context)
                    )
            process.assert_not_awaited()
