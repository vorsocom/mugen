"""Regression tests for connector credential logs and endpoint confinement."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import BadRequest, Conflict
from yarl import URL

from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceInvokeValidation,
)
from mugen.core.plugin.ops_connector.domain import (
    ConnectorCallLogDE,
    ConnectorInstanceDE,
    ConnectorTypeDE,
)
from mugen.core.plugin.ops_connector.service.connector_instance import (
    ConnectorInstanceService,
)


class TestConnectorRequestBoundaries(unittest.IsolatedAsyncioTestCase):
    """Exercise real request construction and call-log persistence boundaries."""

    def setUp(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.instance_id = uuid.uuid4()
        self.secret = "synthetic-connector-credential"
        self.instance = ConnectorInstanceDE(
            id=self.instance_id,
            tenant_id=self.tenant_id,
            connector_type_id=uuid.uuid4(),
            row_version=1,
            status="active",
            secret_ref="test-secret-ref",
            config_json={
                "BaseUrl": "https://connector.invalid/v1",
                "DefaultHeaders": {
                    "X-Custom-Credential": "prefix {secret} suffix",
                    "cOoKiE": "session=static-cookie",
                    "X-Diagnostic": "request-context",
                },
            },
        )
        self.capability = {
            "Method": "GET",
            "PathTemplate": "/records/{RecordId}/details",
            "InputPlacement": "json",
            "Headers": {
                "X-Api-Key": "{secret}",
                "X-Other-Credential": "{secret}",
                "X-Private-Metadata": "configured-redaction",
                "Accept": "application/json",
            },
        }
        self.service = ConnectorInstanceService(
            table="ops_connector_instance",
            rsg=Mock(),
            config_provider=lambda: SimpleNamespace(
                ops_connector=SimpleNamespace(redacted_keys=["x-private-metadata"])
            ),
        )
        self.service._runtime_config_profile_service = SimpleNamespace(
            resolve_active_settings=AsyncMock(return_value={})
        )
        self.service._get_for_action = AsyncMock(return_value=self.instance)
        self.service._connector_type_service = SimpleNamespace(
            get=AsyncMock(
                return_value=ConnectorTypeDE(
                    id=self.instance.connector_type_id,
                    adapter_kind="http_json",
                    is_active=True,
                    capabilities_json={"lookup": self.capability},
                )
            )
        )
        self.service._resolve_secret_material = AsyncMock(
            return_value=ResolvedKeyMaterial(
                key_id="test-secret-ref",
                secret=self.secret.encode(),
                provider="local",
            )
        )
        self.service._acquire_dedup = AsyncMock(
            return_value={"enabled": False, "replay": None}
        )
        self.service._commit_dedup_success = AsyncMock()
        self.service._commit_dedup_failure = AsyncMock()
        self.service._emit_connector_biz_trace = AsyncMock()
        self.service._run_failure_escalation = AsyncMock(return_value=None)
        self.service._execute_http_request = AsyncMock(
            return_value={
                "ok": True,
                "status_code": 200,
                "payload": {"record": "example"},
                "attempt_count": 1,
            }
        )
        self.service._call_log_service = SimpleNamespace(
            create=AsyncMock(return_value=ConnectorCallLogDE(id=uuid.uuid4()))
        )

    async def _invoke(self, input_json: object) -> tuple[dict, int]:
        return await self.service.action_invoke(
            tenant_id=self.tenant_id,
            entity_id=self.instance_id,
            where={"tenant_id": self.tenant_id, "id": self.instance_id},
            auth_user_id=uuid.uuid4(),
            data=ConnectorInstanceInvokeValidation(
                row_version=1,
                capability_name="lookup",
                input_json=input_json,
            ),
        )

    async def test_invoke_redacts_credentials_without_changing_sent_headers(
        self,
    ) -> None:
        for succeeded in (True, False):
            with self.subTest(succeeded=succeeded):
                self.service._execute_http_request.return_value["ok"] = succeeded
                self.service._execute_http_request.return_value["status_code"] = (
                    200 if succeeded else 500
                )
                _payload, code = await self._invoke({"RecordId": "record-1"})
                self.assertEqual(code, 200 if succeeded else 502)

                sent = self.service._execute_http_request.await_args.kwargs["headers"]
                self.assertEqual(sent["X-Api-Key"], self.secret)
                self.assertEqual(sent["Authorization"], f"Bearer {self.secret}")
                self.assertEqual(sent["cOoKiE"], "session=static-cookie")
                self.assertEqual(
                    sent["X-Custom-Credential"], f"prefix {self.secret} suffix"
                )

                persisted = self.service._call_log_service.create.await_args.args[0]
                logged = persisted["request_json"]["Headers"]
                for name in (
                    "Authorization",
                    "X-Api-Key",
                    "X-Custom-Credential",
                    "X-Other-Credential",
                    "X-Private-Metadata",
                    "cOoKiE",
                ):
                    self.assertEqual(logged[name], "***REDACTED***")
                self.assertNotIn(self.secret, json.dumps(persisted["request_json"]))
                self.assertEqual(logged["Accept"], "application/json")
                self.assertEqual(logged["X-Diagnostic"], "request-context")

    def test_header_redaction_cannot_disable_standard_credential_names(self) -> None:
        headers = {
            "Authorization": "literal-token",
            "Proxy-Authorization": "literal-proxy-token",
            "Set-Cookie": "session=literal-cookie",
            "X-Api-Key": "literal-api-key",
            "X-Diagnostic": "safe-value",
        }
        logged = self.service._redact_request_headers(
            headers,
            secret_text="",
            redacted_keys=(),
        )
        self.assertEqual(logged["X-Diagnostic"], "safe-value")
        for name in headers.keys() - {"X-Diagnostic"}:
            self.assertEqual(logged[name], "***REDACTED***")

    async def test_invoke_rejects_unsafe_path_values_before_outbound_request(
        self,
    ) -> None:
        for value in (
            "",
            ".",
            "..",
            "../../admin",
            "record/other",
            "..\\admin",
            "//elsewhere.invalid/",
            "record?admin=true",
            "record#remove-suffix",
            "%2e%2e%2fadmin",
            "%252e%252e%252fadmin",
            "%253fadmin=true",
            "%23remove-suffix",
            "%5cadmin",
            "record\nadmin",
            "record\x00admin",
            "record\x7fadmin",
            None,
            ["record"],
            {"name": "record"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(BadRequest):
                    await self._invoke({"RecordId": value})
                self.service._execute_http_request.assert_not_awaited()
                self.service._call_log_service.create.assert_not_awaited()

    async def test_invoke_rejects_missing_path_values(self) -> None:
        for input_json in ({}, [], None):
            with self.subTest(input_json=input_json):
                with self.assertRaises(BadRequest):
                    await self._invoke(input_json)
                self.service._execute_http_request.assert_not_awaited()

    async def test_invoke_encodes_values_and_preserves_unrelated_input(self) -> None:
        for value, expected_segment in (
            ("record-1", "record-1"),
            ("résumé one", "r%C3%A9sum%C3%A9%20one"),
            (42, "42"),
            (False, "False"),
            (1.5, "1.5"),
            ("a..b", "a..b"),
        ):
            with self.subTest(value=value):
                data = {"RecordId": value, "payload": {"url": "../other?q=a#b"}}
                _payload, code = await self._invoke(data)
                self.assertEqual(code, 200)
                sent = self.service._execute_http_request.await_args.kwargs
                url = URL(sent["url"])
                self.assertEqual(str(url.origin()), "https://connector.invalid")
                self.assertEqual(
                    url.raw_path,
                    f"/v1/records/{expected_segment}/details",
                )
                self.assertEqual(url.query_string, "")
                self.assertEqual(url.fragment, "")
                self.assertEqual(sent["body_json"], data)

    def test_request_spec_preserves_non_path_payload_placements(self) -> None:
        for placement in ("json", "query", "text", "body"):
            with self.subTest(placement=placement):
                data = {"RecordId": "record-1", "filter": "../other?q=a#b"}
                self.capability["InputPlacement"] = placement
                _method, url, params, _headers, text_body, json_body = (
                    self.service._invoke_request_spec(
                        base_url="https://connector.invalid/v1",
                        capability=self.capability,
                        input_json=data,
                    )
                )
                self.assertEqual(URL(url).raw_path, "/v1/records/record-1/details")
                if placement == "query":
                    self.assertEqual(json.loads(params["filter"]), data["filter"])
                elif placement in {"text", "body"}:
                    self.assertEqual(json.loads(text_body), data)
                else:
                    self.assertEqual(json_body, data)

    def test_request_spec_accepts_static_paths_and_scalar_payloads(self) -> None:
        self.capability["PathTemplate"] = "/.well-known/jwks.json"
        self.capability["InputPlacement"] = "query"
        _method, url, params, *_ = self.service._invoke_request_spec(
            base_url="https://connector.invalid/v1",
            capability=self.capability,
            input_json=["payload", "../allowed-in-body"],
        )
        self.assertEqual(URL(url).raw_path, "/v1/.well-known/jwks.json")
        self.assertEqual(json.loads(params["input"]), ["payload", "../allowed-in-body"])

    def test_request_spec_rejects_invalid_path_templates(self) -> None:
        for template in (
            "records/{RecordId}",
            "//elsewhere.invalid/{RecordId}",
            "/records/../{RecordId}",
            "/records/./{RecordId}",
            "/records/%2e%2e/{RecordId}",
            "/records/{RecordId}?admin=true",
            "/records/{RecordId}#suffix",
            "/records\\{RecordId}",
            "/records/\x00{RecordId}",
            "/records/{RecordId",
            "/records/{}",
            "/records/{RecordId!r}",
            "/records/{RecordId:>8}",
            "/records/{RecordId.__class__}",
            "/records/{RecordId[0]}",
        ):
            with self.subTest(template=template):
                self.capability["PathTemplate"] = template
                with self.assertRaises(Conflict):
                    self.service._invoke_request_spec(
                        base_url="https://connector.invalid/v1",
                        capability=self.capability,
                        input_json={"RecordId": "record-1"},
                    )
