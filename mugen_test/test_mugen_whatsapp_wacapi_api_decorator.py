"""Unit tests for mugen.core.plugin.whatsapp.wacapi.api.decorator."""

import hashlib
import hmac
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from werkzeug.exceptions import BadRequest

from mugen.core.plugin.whatsapp.wacapi.api import decorator as whatsapp_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(
    *,
    platforms: list[str] | None = None,
    verify_ip: bool = False,
    trust_forwarded_for: bool = False,
    basedir: str = "",
    allow_file: str = "",
):
    return SimpleNamespace(
        basedir=basedir,
        mugen=SimpleNamespace(platforms=list(platforms or ["whatsapp"])),
        whatsapp=SimpleNamespace(
            servers=SimpleNamespace(
                allowed=allow_file,
                verify_ip=verify_ip,
                trust_forwarded_for=trust_forwarded_for,
            ),
        ),
    )


def _make_client_profile(
    *,
    path_token: str = "expected-path",
    phone_number_id: str | None = "123456789",
    profile_id: str = "00000000-0000-0000-0000-000000000401",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=profile_id,
        platform_key="whatsapp",
        path_token=path_token,
        phone_number_id=phone_number_id,
    )


def _make_runtime_config(*, app_secret: str = "app-secret") -> SimpleNamespace:
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            app=SimpleNamespace(secret=app_secret),
        )
    )


def _signed_request(
    body: bytes,
    *,
    secret: str = "profile-secret",
    signature: object | None = None,
    include_signature: bool = True,
) -> SimpleNamespace:
    digest = hmac.new(secret.encode("utf8"), body, hashlib.sha256).hexdigest()
    headers = {}
    if include_signature:
        headers["X-Hub-Signature-256"] = (
            f"sha256={digest}" if signature is None else signature
        )
    return SimpleNamespace(headers=headers, get_data=AsyncMock(return_value=body))


class TestMugenWhatsAppWacapiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, signature, and IP allow-list decorators."""

    def setUp(self) -> None:
        whatsapp_decorator._WEBHOOK_METRICS.clear()  # pylint: disable=protected-access

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(whatsapp_decorator.di, "container", new=container):
            self.assertEqual(whatsapp_decorator._config_provider(), "cfg")
            self.assertEqual(whatsapp_decorator._logger_provider(), "logger")
            self.assertIsNone(whatsapp_decorator._client_profile_service())

        with patch.object(
            whatsapp_decorator,
            "MessagingClientProfileService",
            return_value="service",
        ) as service_cls:
            container = SimpleNamespace(
                config="cfg",
                logging_gateway="logger",
                relational_storage_gateway="rsg",
            )
            with patch.object(whatsapp_decorator.di, "container", new=container):
                self.assertEqual(
                    whatsapp_decorator._client_profile_service(),
                    "service",
                )
        service_cls.assert_called_once_with(
            table="admin_messaging_client_profile",
            rsg="rsg",
        )

    def test_webhook_context_helpers_are_stable_and_sanitized(self) -> None:
        first = whatsapp_decorator._new_webhook_context(b"same-body")
        retry = whatsapp_decorator._new_webhook_context(b"same-body")
        different = whatsapp_decorator._new_webhook_context(b"different-body")

        self.assertEqual(first.payload_fingerprint, retry.payload_fingerprint)
        self.assertNotEqual(first.payload_fingerprint, different.payload_fingerprint)
        self.assertEqual(len(first.payload_fingerprint), 16)
        self.assertNotEqual(first.request_id, retry.request_id)
        self.assertEqual(
            whatsapp_decorator._safe_client_profile_id(_make_client_profile()),
            "00000000-0000-0000-0000-000000000401",
        )
        self.assertIsNone(
            whatsapp_decorator._safe_client_profile_id(
                _make_client_profile(profile_id="unsafe secret value")
            )
        )
        self.assertEqual(
            whatsapp_decorator._safe_change_field("messages"),
            "messages",
        )
        self.assertEqual(
            whatsapp_decorator._safe_change_field("attacker-controlled-field"),
            "unknown",
        )
        self.assertEqual(whatsapp_decorator._safe_change_field(None), "unknown")

        whatsapp_decorator._increment_webhook_metric("received", "total")
        snapshot = whatsapp_decorator.webhook_metrics_snapshot()
        snapshot["whatsapp.webhook.received.total"] = 99
        self.assertEqual(
            whatsapp_decorator.webhook_metrics_snapshot()[
                "whatsapp.webhook.received.total"
            ],
            1,
        )

    def test_extract_change_phone_number_id_handles_shapes(self) -> None:
        self.assertIsNone(whatsapp_decorator._extract_change_phone_number_id({}))
        self.assertIsNone(
            whatsapp_decorator._extract_change_phone_number_id({"value": []})
        )
        self.assertIsNone(
            whatsapp_decorator._extract_change_phone_number_id(
                {"value": {"metadata": []}}
            )
        )
        self.assertIsNone(
            whatsapp_decorator._extract_change_phone_number_id(
                {"value": {"metadata": {"phone_number_id": None}}}
            )
        )
        self.assertIsNone(
            whatsapp_decorator._extract_change_phone_number_id(
                {"value": {"metadata": {"phone_number_id": "  "}}}
            )
        )
        self.assertEqual(
            whatsapp_decorator._extract_change_phone_number_id(
                {
                    "value": {
                        "metadata": {
                            "phone_number_id": " 123456789 ",
                        }
                    }
                }
            ),
            "123456789",
        )

    async def test_whatsapp_platform_required_paths(self) -> None:
        logger = Mock()

        async def _ok_handler(**_kwargs):
            return {"ok": True}

        with patch.object(
            whatsapp_decorator, "abort", side_effect=_abort_raiser
        ) as abort_mock:
            guarded = whatsapp_decorator.whatsapp_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(platforms=["matrix"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("WhatsApp platform not enabled.")
            abort_mock.assert_called_once_with(501)

        logger = Mock()
        with patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser):
            guarded = whatsapp_decorator.whatsapp_platform_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Could not get platform configuration."
            )

        guarded = whatsapp_decorator.whatsapp_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(platforms=["whatsapp", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        guarded_factory = whatsapp_decorator.whatsapp_platform_required(
            config_provider=lambda: _make_config(platforms=["whatsapp"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

    async def _execute_signature_guard(
        self,
        *,
        body: bytes,
        service=...,
        handler=None,
        path_token: str | None = "expected-path",
        signature: object | None = None,
        include_signature: bool = True,
        use_factory: bool = False,
    ):
        if service is ...:
            service = SimpleNamespace(
                resolve_active_by_identifier=AsyncMock(
                    return_value=_make_client_profile()
                ),
                build_runtime_config=AsyncMock(
                    return_value=_make_runtime_config(app_secret="profile-secret")
                ),
            )
        if handler is None:
            handler = AsyncMock(return_value={"ok": True})
        logger = Mock()
        request_mock = _signed_request(
            body,
            signature=signature,
            include_signature=include_signature,
        )
        kwargs = {}
        if path_token is not None:
            kwargs["path_token"] = path_token

        with (
            patch.object(
                whatsapp_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(whatsapp_decorator, "request", new=request_mock),
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
        ):
            if use_factory:
                decorator = (
                    whatsapp_decorator.whatsapp_request_signature_verification_required(
                        config_provider=lambda: _make_config(),
                        logger_provider=lambda: logger,
                    )
                )
                guarded = decorator(handler)
            else:
                guarded = (
                    whatsapp_decorator.whatsapp_request_signature_verification_required(
                        handler,
                        config_provider=lambda: _make_config(),
                        logger_provider=lambda: logger,
                    )
                )
            try:
                result = await guarded(**kwargs)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                return None, exc, logger, handler, request_mock, service
        return result, None, logger, handler, request_mock, service

    async def test_signature_guard_resolves_profile_after_reading_raw_body(
        self,
    ) -> None:
        body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
        request_mock = _signed_request(body)

        async def _resolve(**_kwargs):
            self.assertEqual(request_mock.get_data.await_count, 1)
            return _make_client_profile()

        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(side_effect=_resolve),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(app_secret="profile-secret")
            ),
        )
        logger = Mock()
        handler = AsyncMock(return_value={"ok": True})
        with (
            patch.object(
                whatsapp_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(whatsapp_decorator, "request", new=request_mock),
        ):
            guarded = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    handler,
                    config_provider=lambda: _make_config(),
                    logger_provider=lambda: logger,
                )
            )
            self.assertEqual(
                await guarded(path_token="expected-path"),
                {"ok": True},
            )

        context = handler.await_args.kwargs["whatsapp_webhook_context"]
        self.assertEqual(context.entry_count, 0)
        self.assertEqual(context.message_change_count, 0)
        self.assertEqual(context.filtered_payload["entry"], [])
        logger.info.assert_called_once()
        self.assertIn(
            "reason_code=unsupported_change_field", logger.info.call_args.args[0]
        )

    async def test_signature_guard_profile_resolution_failures(self) -> None:
        body = b"not-json-and-never-parsed"
        cases = (
            (None, "expected-path", 500, "error"),
            (
                SimpleNamespace(
                    resolve_active_by_identifier=AsyncMock(
                        side_effect=RuntimeError("database")
                    ),
                    build_runtime_config=AsyncMock(),
                ),
                "expected-path",
                500,
                "error",
            ),
            (
                SimpleNamespace(
                    resolve_active_by_identifier=AsyncMock(return_value=None),
                    build_runtime_config=AsyncMock(),
                ),
                "expected-path",
                401,
                "warning",
            ),
            (
                SimpleNamespace(
                    resolve_active_by_identifier=AsyncMock(
                        return_value=_make_client_profile()
                    ),
                    build_runtime_config=AsyncMock(
                        side_effect=KeyError("missing secret")
                    ),
                ),
                "expected-path",
                500,
                "error",
            ),
        )
        for service, path_token, status, level in cases:
            with self.subTest(status=status, level=level, service=service):
                (
                    _result,
                    exc,
                    logger,
                    handler,
                    request_mock,
                    _service,
                ) = await self._execute_signature_guard(
                    body=body,
                    service=service,
                    path_token=path_token,
                )
                self.assertIsInstance(exc, _AbortCalled)
                self.assertEqual(exc.code, status)
                handler.assert_not_awaited()
                request_mock.get_data.assert_awaited_once()
                log_message = getattr(logger, level).call_args.args[0]
                self.assertIn("reason_code=profile_resolution_failed", log_message)
                self.assertNotIn("not-json-and-never-parsed", log_message)

        (
            _result,
            exc,
            logger,
            _handler,
            _request_mock,
            service,
        ) = await self._execute_signature_guard(
            body=body,
            path_token=None,
        )
        self.assertIsInstance(exc, _AbortCalled)
        self.assertEqual(exc.code, 400)
        service.resolve_active_by_identifier.assert_not_awaited()
        self.assertIn(
            "reason_code=profile_resolution_failed",
            logger.warning.call_args.args[0],
        )

    async def test_signature_guard_rejects_missing_and_invalid_signatures_first(
        self,
    ) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "15551234567",
                                        "text": {"body": "customer secret"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()

        for signature, include_signature, expected_status, reason_code in (
            (None, False, 400, "missing_signature"),
            ("", True, 400, "missing_signature"),
            ("sha256=deadbeef", True, 401, "invalid_signature"),
            (123, True, 400, "missing_signature"),
        ):
            with self.subTest(reason_code=reason_code, signature=signature):
                (
                    _result,
                    exc,
                    logger,
                    handler,
                    _request_mock,
                    _service,
                ) = await self._execute_signature_guard(
                    body=body,
                    signature=signature,
                    include_signature=include_signature,
                )
                self.assertIsInstance(exc, _AbortCalled)
                self.assertEqual(exc.code, expected_status)
                handler.assert_not_awaited()
                logger.error.assert_not_called()
                log_message = logger.warning.call_args.args[0]
                self.assertIn(f"reason_code={reason_code}", log_message)
                self.assertNotIn("missing_phone_number_id_for_messages", log_message)
                self.assertNotIn("15551234567", log_message)
                self.assertNotIn("customer secret", log_message)
                self.assertNotIn("expected-path", log_message)
                self.assertNotIn("deadbeef", log_message)

    async def test_signature_guard_rejects_authenticated_malformed_json(self) -> None:
        for body in (b"not-json", b"\xff"):
            whatsapp_decorator._WEBHOOK_METRICS.clear()
            with self.subTest(body=body):
                (
                    _result,
                    exc,
                    logger,
                    handler,
                    _request_mock,
                    _service,
                ) = await self._execute_signature_guard(body=body)
                self.assertIsInstance(exc, _AbortCalled)
                self.assertEqual(exc.code, 400)
                handler.assert_not_awaited()
                self.assertIn(
                    "reason_code=malformed_json",
                    logger.error.call_args.args[0],
                )
                self.assertEqual(
                    whatsapp_decorator.webhook_metrics_snapshot()[
                        "whatsapp.webhook.authenticated.total"
                    ],
                    1,
                )

    async def test_signature_guard_rejects_authenticated_malformed_shapes(self) -> None:
        malformed_payloads = (
            [],
            {},
            {"entry": ["bad-entry"]},
            {"entry": [{}]},
            {"entry": [{"changes": "bad-changes"}]},
            {"entry": [{"changes": ["bad-change"]}]},
        )
        for payload in malformed_payloads:
            whatsapp_decorator._WEBHOOK_METRICS.clear()
            body = json.dumps(payload).encode()
            with self.subTest(payload=payload):
                (
                    _result,
                    exc,
                    logger,
                    handler,
                    _request_mock,
                    _service,
                ) = await self._execute_signature_guard(body=body)
                self.assertIsInstance(exc, _AbortCalled)
                self.assertEqual(exc.code, 400)
                handler.assert_not_awaited()
                self.assertIn(
                    "reason_code=malformed_payload",
                    logger.error.call_args.args[0],
                )

    async def test_signature_guard_validates_every_message_change_phone_id(
        self,
    ) -> None:
        missing_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {"statuses": [{"status": "sent"}]},
                        }
                    ]
                }
            ],
        }
        (
            _result,
            exc,
            logger,
            handler,
            _request_mock,
            _service,
        ) = await self._execute_signature_guard(
            body=json.dumps(missing_payload).encode()
        )
        self.assertIsInstance(exc, _AbortCalled)
        self.assertEqual(exc.code, 400)
        handler.assert_not_awaited()
        self.assertIn(
            "reason_code=missing_phone_number_id_for_messages",
            logger.error.call_args.args[0],
        )

        mismatch_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "wrong-phone-id"},
                                "messages": [],
                            },
                        }
                    ]
                }
            ],
        }
        (
            _result,
            exc,
            logger,
            handler,
            _request_mock,
            _service,
        ) = await self._execute_signature_guard(
            body=json.dumps(mismatch_payload).encode()
        )
        self.assertIsInstance(exc, _AbortCalled)
        self.assertEqual(exc.code, 401)
        handler.assert_not_awaited()
        log_message = logger.warning.call_args.args[0]
        self.assertIn("reason_code=phone_number_id_mismatch", log_message)
        self.assertNotIn("wrong-phone-id", log_message)
        self.assertNotIn("123456789", log_message)

    async def test_signature_guard_acknowledges_waba_fields_without_phone_metadata(
        self,
    ) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-1",
                    "changes": [
                        {
                            "field": "message_template_status_update",
                            "value": {
                                "message_template_name": "customer-template-secret"
                            },
                        },
                        {"field": "account_update", "value": {"event": "BANNED"}},
                    ],
                },
                {
                    "id": "waba-2",
                    "changes": [
                        {
                            "field": "phone_number_quality_update",
                            "value": {"display_phone_number": "15557654321"},
                        },
                        {
                            "field": "attacker-controlled-field",
                            "value": {"access_token": "token-secret"},
                        },
                    ],
                },
            ],
        }
        (
            result,
            exc,
            logger,
            handler,
            _request_mock,
            _service,
        ) = await self._execute_signature_guard(
            body=json.dumps(payload).encode(),
            use_factory=True,
        )

        self.assertIsNone(exc)
        self.assertEqual(result, {"ok": True})
        context = handler.await_args.kwargs["whatsapp_webhook_context"]
        self.assertEqual(context.filtered_payload["entry"], [])
        self.assertEqual(context.entry_count, 2)
        self.assertEqual(context.change_count, 4)
        self.assertEqual(
            context.change_fields,
            (
                "account_update",
                "message_template_status_update",
                "phone_number_quality_update",
                "unknown",
            ),
        )
        self.assertEqual(context.message_change_count, 0)
        logger.error.assert_not_called()
        logger.warning.assert_not_called()
        log_message = logger.info.call_args.args[0]
        self.assertIn("outcome=ignored", log_message)
        self.assertIn("reason_code=unsupported_change_field", log_message)
        for sensitive in (
            "waba-1",
            "waba-2",
            "customer-template-secret",
            "15557654321",
            "attacker-controlled-field",
            "token-secret",
            "expected-path",
            "profile-secret",
        ):
            self.assertNotIn(sensitive, log_message)
        metrics = whatsapp_decorator.webhook_metrics_snapshot()
        self.assertEqual(
            metrics["whatsapp.webhook.ignored.message_template_status_update"],
            1,
        )
        self.assertEqual(metrics["whatsapp.webhook.ignored.account_update"], 1)
        self.assertEqual(
            metrics["whatsapp.webhook.ignored.phone_number_quality_update"],
            1,
        )
        self.assertEqual(metrics["whatsapp.webhook.ignored.unknown"], 1)

    async def test_signature_guard_filters_mixed_entries_and_accepts_statuses(
        self,
    ) -> None:
        statuses = [
            {"id": "wamid-status", "status": transition}
            for transition in ("sent", "delivered", "read", "failed")
        ]
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "entry-message",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {
                                    "phone_number_id": "123456789",
                                    "display_phone_number": "15551230000",
                                },
                                "contacts": [{"wa_id": "15551230001"}],
                                "messages": [
                                    {
                                        "id": "wamid-message",
                                        "from": "15551230001",
                                        "text": {"body": "private message"},
                                    }
                                ],
                            },
                        },
                        {
                            "field": "message_template_status_update",
                            "value": {"reason": "private template reason"},
                        },
                    ],
                },
                {
                    "id": "entry-status",
                    "changes": [
                        {
                            "field": "account_update",
                            "value": {"event": "private account event"},
                        },
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {
                                    "phone_number_id": "123456789",
                                },
                                "statuses": statuses,
                            },
                        },
                    ],
                },
            ],
        }
        (
            result,
            exc,
            logger,
            handler,
            request_mock,
            _service,
        ) = await self._execute_signature_guard(body=json.dumps(payload).encode())

        self.assertIsNone(exc)
        self.assertEqual(result, {"ok": True})
        context = handler.await_args.kwargs["whatsapp_webhook_context"]
        filtered_entries = context.filtered_payload["entry"]
        self.assertEqual(len(filtered_entries), 2)
        self.assertEqual(
            [
                change["field"]
                for entry in filtered_entries
                for change in entry["changes"]
            ],
            ["messages", "messages"],
        )
        self.assertEqual(
            filtered_entries[1]["changes"][0]["value"]["statuses"],
            statuses,
        )
        self.assertEqual(context.message_change_count, 2)
        self.assertEqual(context.change_count, 4)
        self.assertEqual(logger.info.call_count, 2)
        combined_logs = " ".join(call.args[0] for call in logger.info.call_args_list)
        self.assertIn("reason_code=unsupported_change_field", combined_logs)
        self.assertIn("reason_code=message_event_accepted", combined_logs)
        signature = request_mock.headers["X-Hub-Signature-256"]
        for sensitive in (
            "15551230000",
            "15551230001",
            "123456789",
            "private message",
            "private template reason",
            "private account event",
            "expected-path",
            "profile-secret",
            signature,
        ):
            self.assertNotIn(sensitive, combined_logs)
        metrics = whatsapp_decorator.webhook_metrics_snapshot()
        self.assertEqual(metrics["whatsapp.webhook.received.total"], 1)
        self.assertEqual(metrics["whatsapp.webhook.authenticated.total"], 1)
        self.assertEqual(metrics["whatsapp.webhook.accepted.messages"], 2)
        self.assertEqual(
            metrics["whatsapp.webhook.ignored.message_template_status_update"],
            1,
        )
        self.assertEqual(metrics["whatsapp.webhook.ignored.account_update"], 1)

    async def test_signature_guard_sanitizes_profile_and_object_values(self) -> None:
        payload = {
            "object": "object-secret",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "unknown-secret-field",
                            "value": {},
                        }
                    ]
                }
            ],
        }
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(profile_id="profile-secret")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(app_secret="profile-secret")
            ),
        )
        (
            _result,
            exc,
            logger,
            _handler,
            _request_mock,
            _service,
        ) = await self._execute_signature_guard(
            body=json.dumps(payload).encode(),
            service=service,
        )
        self.assertIsNone(exc)
        log_message = logger.info.call_args.args[0]
        self.assertIn("object_type=unknown", log_message)
        self.assertIn("change_fields=unknown", log_message)
        self.assertIn("client_profile_id=unresolved", log_message)
        self.assertNotIn("object-secret", log_message)
        self.assertNotIn("unknown-secret-field", log_message)
        self.assertNotIn("profile-secret", log_message)

    async def test_signature_guard_records_handler_failures_safely(self) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456789"},
                                "messages": [],
                            },
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()
        for raised, expected_status in (
            (BadRequest(), 400),
            (RuntimeError("customer payload secret"), 500),
        ):
            with self.subTest(raised=type(raised).__name__):
                handler = AsyncMock(side_effect=raised)
                (
                    _result,
                    exc,
                    logger,
                    _handler,
                    _request_mock,
                    _service,
                ) = await self._execute_signature_guard(
                    body=body,
                    handler=handler,
                )
                self.assertIs(exc, raised)
                log_message = logger.error.call_args.args[0]
                self.assertIn("reason_code=routing_failure", log_message)
                self.assertIn(f"http_status={expected_status}", log_message)
                self.assertNotIn("customer payload secret", log_message)

    async def test_whatsapp_server_ip_allow_list_required_paths(self) -> None:
        async def _ok_handler():
            return {"ok": True}

        guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
            _ok_handler,
            config_provider=lambda: _make_config(
                verify_ip=False,
                basedir="/tmp",
                allow_file="missing.txt",
            ),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(whatsapp=SimpleNamespace()),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once_with(
            "WhatsApp IP verification configuration missing."
        )

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(
                    whatsapp=SimpleNamespace(servers=SimpleNamespace(verify_ip="yes"))
                ),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once_with(
            "WhatsApp IP verification configuration invalid."
        )

        guarded_factory = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
            config_provider=lambda: _make_config(verify_ip=False),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    remote_addr=None,
                    headers={},
                ),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: _make_config(
                    verify_ip=True,
                    basedir="/tmp",
                    allow_file="missing.txt",
                ),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "WhatsApp servers allow list not found."
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            allow_file = "allow.list.txt"
            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("10.0.0.0/24\n")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr=None, headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 400)
                logger.error.assert_called_once_with(
                    "Remote address could not be determined."
                )

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr="bad-ip", headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 400)
                logger.error.assert_called_once_with("Remote address is invalid.")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr="10.0.1.1", headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 403)
                logger.error.assert_called_once_with(
                    "Remote address not in allow list."
                )

            with (
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: Mock(),
                )
                self.assertEqual(await guarded(), {"ok": True})

            with (
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        trust_forwarded_for=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: Mock(),
                )
                self.assertEqual(await guarded(), {"ok": True})

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(
                        remote_addr="10.0.0.10",
                        headers={"X-Forwarded-For": "10.0.1.1, 10.0.0.10"},
                    ),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        trust_forwarded_for=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 403)
                logger.error.assert_called_once_with(
                    "Remote address not in allow list."
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            allow_file = "allow.list.txt"
            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("not-a-cidr\n")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 500)
                logger.error.assert_called_once_with(
                    "Invalid CIDR entry in WhatsApp allow list."
                )
