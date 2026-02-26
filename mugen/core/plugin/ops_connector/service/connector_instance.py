"""Provides invoke/test actions for ops_connector connector instances."""

__all__ = ["ConnectorInstanceService"]

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Mapping
import uuid

import aiohttp
from quart import abort
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.api.audit import emit_biz_trace_event
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.service.dedup_record import DedupRecordService
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.plugin.acp.service.schema_definition import SchemaDefinitionService
from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceCreateValidation,
    ConnectorInstanceInvokeValidation,
    ConnectorInstanceTestConnectionValidation,
)
from mugen.core.plugin.ops_connector.contract.service.connector_instance import (
    IConnectorInstanceService,
)
from mugen.core.plugin.ops_connector.domain import ConnectorInstanceDE, ConnectorTypeDE
from mugen.core.plugin.ops_connector.service.connector_call_log import (
    ConnectorCallLogService,
)
from mugen.core.plugin.ops_connector.service.connector_type import ConnectorTypeService
from mugen.core.plugin.ops_sla.api.validation import SlaEscalationExecuteValidation
from mugen.core.plugin.ops_sla.service.sla_escalation_policy import (
    SlaEscalationPolicyService,
)


def _config_provider():
    return di.container.config


def _registry_provider():  # pragma: no cover
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:  # pragma: no cover
        return "{" + key + "}"


class ConnectorInstanceService(  # pragma: no cover
    IRelationalService[ConnectorInstanceDE],
    IConnectorInstanceService,
):
    """A CRUD/action service for tenant connector invocation runtime."""

    _TYPE_TABLE = "ops_connector_type"
    _CALL_LOG_TABLE = "ops_connector_call_log"
    _KEY_REF_TABLE = "admin_key_ref"
    _SCHEMA_DEFINITION_TABLE = "admin_schema_definition"
    _DEDUP_RECORD_TABLE = "admin_dedup_record"
    _SLA_ESCALATION_POLICY_TABLE = "ops_sla_escalation_policy"

    _PLUGIN_NAMESPACE = "com.vorsocomputing.mugen.ops_connector"
    _DEFAULT_RETRY_CODES = (429, 500, 502, 503, 504)

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=ConnectorInstanceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._config_provider = config_provider
        self._registry_provider = registry_provider

        self._connector_type_service = ConnectorTypeService(
            table=self._TYPE_TABLE, rsg=rsg
        )
        self._call_log_service = ConnectorCallLogService(
            table=self._CALL_LOG_TABLE, rsg=rsg
        )
        self._key_ref_service = KeyRefService(table=self._KEY_REF_TABLE, rsg=rsg)
        self._schema_definition_service = SchemaDefinitionService(
            table=self._SCHEMA_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._dedup_service = DedupRecordService(
            table=self._DEDUP_RECORD_TABLE, rsg=rsg
        )
        self._sla_escalation_policy_service = SlaEscalationPolicyService(
            table=self._SLA_ESCALATION_POLICY_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _normalize_capability_name(value: str) -> str:
        return str(value or "").strip().casefold()

    @staticmethod
    def _normalize_status(value: Any) -> str:
        return str(getattr(value, "value", value) or "").casefold()

    @staticmethod
    def _parse_positive_int(value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return int(default)
        if parsed < 0:
            return int(default)
        return parsed

    @staticmethod
    def _parse_positive_float(
        value: Any, *, default: float, minimum: float = 0.0
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return float(default)
        if parsed <= minimum:
            return float(default)
        return parsed

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()

        if isinstance(value, Mapping):
            return {str(k): cls._json_safe(v) for k, v in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(v) for v in value]

        if hasattr(value, "__dict__"):
            return {
                str(k): cls._json_safe(v)
                for k, v in vars(value).items()
                if not str(k).startswith("_")
            }

        return str(value)

    @classmethod
    def _canonical_json_bytes(cls, value: Any) -> bytes:
        return json.dumps(
            cls._json_safe(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def _sha256_hex(cls, value: Any) -> str:
        return hashlib.sha256(
            cls._canonical_json_bytes(value)
        ).hexdigest()  # noqa: S324

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, SimpleNamespace):
            return vars(value)
        return {}

    def _connector_config(self) -> SimpleNamespace:
        root = self._config_provider()
        cfg = getattr(root, "ops_connector", SimpleNamespace())

        timeout_seconds_default = self._parse_positive_float(
            getattr(cfg, "timeout_seconds_default", 10.0),
            default=10.0,
            minimum=0.0,
        )
        max_retries_default = self._parse_positive_int(
            getattr(cfg, "max_retries_default", 2),
            default=2,
        )
        retry_backoff_seconds_default = self._parse_positive_float(
            getattr(cfg, "retry_backoff_seconds_default", 0.5),
            default=0.5,
            minimum=-1.0,
        )

        raw_codes = getattr(cfg, "retry_status_codes_default", None)
        if isinstance(raw_codes, (list, tuple, set)):
            retry_status_codes_default = tuple(
                code
                for code in [
                    int(item) for item in raw_codes if str(item).strip().isdigit()
                ]
                if 100 <= code <= 599
            )
            if not retry_status_codes_default:
                retry_status_codes_default = self._DEFAULT_RETRY_CODES
        else:
            retry_status_codes_default = self._DEFAULT_RETRY_CODES

        redacted_keys_raw = getattr(
            cfg,
            "redacted_keys",
            ["password", "token", "secret", "authorization", "api_key"],
        )
        if isinstance(redacted_keys_raw, (list, tuple, set)):
            redacted_keys = tuple(
                str(item).strip().casefold()
                for item in redacted_keys_raw
                if str(item).strip()
            )
        else:
            redacted_keys = (
                "password",
                "token",
                "secret",
                "authorization",
                "api_key",
            )

        secret_purpose = (
            self._normalize_optional_text(
                getattr(cfg, "secret_purpose", "ops_connector_secret")
            )
            or "ops_connector_secret"
        )

        return SimpleNamespace(
            timeout_seconds_default=timeout_seconds_default,
            max_retries_default=max_retries_default,
            retry_backoff_seconds_default=retry_backoff_seconds_default,
            retry_status_codes_default=retry_status_codes_default,
            redacted_keys=redacted_keys,
            secret_purpose=secret_purpose,
        )

    def _safe_registry(self) -> IAdminRegistry | None:
        try:
            return self._registry_provider()
        except Exception:  # pylint: disable=broad-except
            return None

    async def _emit_connector_biz_trace(
        self,
        *,
        stage: str,
        tenant_id: uuid.UUID,
        action_name: str,
        trace_id: str | None,
        status_code: int | None,
        duration_ms: int | None,
        details: Mapping[str, Any] | None,
    ) -> None:
        registry = self._safe_registry()
        if registry is None:
            return

        await emit_biz_trace_event(
            registry=registry,
            stage=stage,
            source_plugin=self._PLUGIN_NAMESPACE,
            entity_set="OpsConnectorInstances",
            action_name=action_name,
            status_code=status_code,
            duration_ms=duration_ms,
            details=details,
            tenant_id=tenant_id,
            trace_id=trace_id,
        )

    def _redact_payload(self, value: Any, *, redacted_keys: tuple[str, ...]) -> Any:
        if isinstance(value, Mapping):
            output: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text.casefold() in redacted_keys:
                    output[key_text] = "***REDACTED***"
                else:
                    output[key_text] = self._redact_payload(
                        item,
                        redacted_keys=redacted_keys,
                    )
            return output

        if isinstance(value, list):
            return [
                self._redact_payload(item, redacted_keys=redacted_keys)
                for item in value
            ]

        if isinstance(value, tuple):
            return [
                self._redact_payload(item, redacted_keys=redacted_keys)
                for item in value
            ]

        if isinstance(value, set):
            return [
                self._redact_payload(item, redacted_keys=redacted_keys)
                for item in sorted(value, key=lambda item: str(item))
            ]

        return value

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ConnectorInstanceDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Connector instance not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ConnectorInstanceDE:
        svc: ICrudServiceWithRowVersion[ConnectorInstanceDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _resolve_connector_type(
        self,
        *,
        connector_type_id: uuid.UUID,
    ) -> ConnectorTypeDE:
        try:
            row = await self._connector_type_service.get({"id": connector_type_id})
        except SQLAlchemyError:
            abort(500)

        if row is None:
            abort(409, "Connector type reference did not resolve.")

        if not bool(row.is_active):
            abort(409, "Connector type is inactive.")

        return row

    def _resolve_capability(
        self,
        *,
        connector_type: ConnectorTypeDE,
        capability_name: str,
    ) -> tuple[str, dict[str, Any]]:
        capabilities = connector_type.capabilities_json or {}
        if not isinstance(capabilities, Mapping):
            abort(409, "ConnectorType.CapabilitiesJson must be an object.")

        requested = self._normalize_capability_name(capability_name)
        if requested == "":
            abort(409, "CapabilityName must be non-empty.")

        for configured_name, definition in capabilities.items():
            configured_key = str(configured_name or "").strip()
            if configured_key.casefold() != requested:
                continue
            if not isinstance(definition, Mapping):
                abort(
                    409,
                    (
                        "Connector capability definitions must be objects. "
                        f"Invalid entry for {configured_key}."
                    ),
                )
            return configured_key, dict(definition)

        abort(
            409, f"CapabilityName {capability_name!r} was not found in ConnectorType."
        )

    async def _resolve_connector_type_id_for_create(
        self,
        *,
        connector_type_id: uuid.UUID | None,
        connector_type_key: str | None,
    ) -> uuid.UUID:
        if connector_type_id is not None:
            resolved = await self._resolve_connector_type(
                connector_type_id=connector_type_id,
            )
            if resolved.id is None:
                abort(409, "Connector type reference did not include an ID.")
            return resolved.id

        key = self._normalize_optional_text(connector_type_key)
        if key is None:
            abort(409, "ConnectorTypeId or ConnectorTypeKey is required.")

        try:
            resolved = await self._connector_type_service.get({"key": key})
        except SQLAlchemyError:
            abort(500)

        if resolved is None:
            abort(409, "ConnectorTypeKey did not resolve to a connector type.")

        if not bool(resolved.is_active):
            abort(409, "Connector type is inactive.")

        if resolved.id is None:
            abort(409, "Connector type reference did not include an ID.")

        return resolved.id

    @staticmethod
    def _schema_ref(
        definition: Mapping[str, Any], field_name: str
    ) -> dict[str, Any] | None:
        raw = definition.get(field_name)
        if raw is None:
            return None

        if not isinstance(raw, Mapping):
            abort(409, f"{field_name} must be an object when provided.")

        schema_definition_id = raw.get("SchemaDefinitionId")
        key = ConnectorInstanceService._normalize_optional_text(raw.get("Key"))
        version_raw = raw.get("Version")

        if schema_definition_id is not None:
            try:
                schema_id = uuid.UUID(str(schema_definition_id))
            except ValueError:
                abort(409, f"{field_name}.SchemaDefinitionId must be a UUID.")
            return {
                "schema_definition_id": schema_id,
                "key": None,
                "version": None,
            }

        if key is None:
            abort(409, f"{field_name} requires SchemaDefinitionId or Key + Version.")

        try:
            version = int(version_raw)
        except (TypeError, ValueError):
            abort(409, f"{field_name}.Version must be a positive integer.")

        if version <= 0:
            abort(409, f"{field_name}.Version must be a positive integer.")

        return {
            "schema_definition_id": None,
            "key": key,
            "version": version,
        }

    async def _validate_input_schema(
        self,
        *,
        tenant_id: uuid.UUID,
        schema_ref: dict[str, Any] | None,
        payload: Any,
    ) -> None:
        if schema_ref is None:
            return

        try:
            _definition, errors = (
                await self._schema_definition_service.validate_payload(
                    tenant_id=tenant_id,
                    schema_definition_id=schema_ref["schema_definition_id"],
                    key=schema_ref["key"],
                    version=schema_ref["version"],
                    payload=payload,
                )
            )
        except HTTPException as exc:
            abort(
                409,
                (
                    "Input schema validation failed because the schema reference "
                    f"could not be resolved: {exc.description}"
                ),
            )

        if errors:
            abort(
                409,
                "Input schema validation failed: "
                + "; ".join(str(item) for item in errors),
            )

    async def _validate_output_schema(
        self,
        *,
        tenant_id: uuid.UUID,
        schema_ref: dict[str, Any] | None,
        payload: Any,
    ) -> list[str]:
        if schema_ref is None:
            return []

        try:
            _definition, errors = (
                await self._schema_definition_service.validate_payload(
                    tenant_id=tenant_id,
                    schema_definition_id=schema_ref["schema_definition_id"],
                    key=schema_ref["key"],
                    version=schema_ref["version"],
                    payload=payload,
                )
            )
        except HTTPException as exc:
            return [f"output_schema_resolution_failed:{exc.description}"]

        return list(errors)

    async def _resolve_secret_material(
        self,
        *,
        tenant_id: uuid.UUID,
        secret_ref: str,
    ) -> ResolvedKeyMaterial:
        cfg = self._connector_config()

        try:
            resolved = await self._key_ref_service.resolve_secret_for_key_id(
                tenant_id=tenant_id,
                purpose=cfg.secret_purpose,
                key_id=secret_ref,
            )
        except SQLAlchemyError:
            abort(500)

        if resolved is None:
            abort(
                409,
                (
                    "Secret resolution failed for SecretRef under purpose "
                    f"{cfg.secret_purpose}."
                ),
            )

        return resolved

    def _resolve_retry_policy(
        self,
        *,
        instance: ConnectorInstanceDE,
        capability: Mapping[str, Any],
    ) -> tuple[float, int, float, tuple[int, ...]]:
        cfg = self._connector_config()

        config_json = (
            instance.config_json if isinstance(instance.config_json, Mapping) else {}
        )
        config_policy = (
            config_json.get("RetryPolicy")
            if isinstance(config_json.get("RetryPolicy"), Mapping)
            else {}
        )
        instance_policy = (
            instance.retry_policy_json
            if isinstance(instance.retry_policy_json, Mapping)
            else {}
        )

        timeout_seconds = self._parse_positive_float(
            capability.get(
                "TimeoutSeconds",
                instance_policy.get(
                    "TimeoutSeconds",
                    config_policy.get("TimeoutSeconds", cfg.timeout_seconds_default),
                ),
            ),
            default=cfg.timeout_seconds_default,
            minimum=0.0,
        )
        max_retries = self._parse_positive_int(
            capability.get(
                "MaxRetries",
                instance_policy.get(
                    "MaxRetries",
                    config_policy.get("MaxRetries", cfg.max_retries_default),
                ),
            ),
            default=cfg.max_retries_default,
        )
        retry_backoff_seconds = self._parse_positive_float(
            capability.get(
                "RetryBackoffSeconds",
                instance_policy.get(
                    "RetryBackoffSeconds",
                    config_policy.get(
                        "RetryBackoffSeconds", cfg.retry_backoff_seconds_default
                    ),
                ),
            ),
            default=cfg.retry_backoff_seconds_default,
            minimum=-1.0,
        )

        codes_raw = capability.get(
            "RetryStatusCodes",
            instance_policy.get(
                "RetryStatusCodes",
                config_policy.get("RetryStatusCodes", cfg.retry_status_codes_default),
            ),
        )
        codes: list[int] = []
        if isinstance(codes_raw, (list, tuple, set)):
            for raw in codes_raw:
                try:
                    code = int(raw)
                except (TypeError, ValueError):
                    continue
                if 100 <= code <= 599 and code not in codes:
                    codes.append(code)

        if not codes:
            codes = list(cfg.retry_status_codes_default)

        return timeout_seconds, max_retries, retry_backoff_seconds, tuple(codes)

    def _resolve_base_url(self, instance: ConnectorInstanceDE) -> str:
        config_json = (
            instance.config_json if isinstance(instance.config_json, Mapping) else {}
        )
        base_url = self._normalize_optional_text(config_json.get("BaseUrl"))
        if base_url is None:
            abort(409, "ConfigJson.BaseUrl must be configured.")
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            abort(409, "ConfigJson.BaseUrl must be an http(s) URL.")
        return base_url.rstrip("/")

    def _resolve_headers(
        self,
        *,
        instance: ConnectorInstanceDE,
        capability: Mapping[str, Any],
        secret_text: str,
    ) -> dict[str, str]:
        config_json = (
            instance.config_json if isinstance(instance.config_json, Mapping) else {}
        )
        default_headers = (
            config_json.get("DefaultHeaders")
            if isinstance(config_json.get("DefaultHeaders"), Mapping)
            else {}
        )
        capability_headers = (
            capability.get("Headers")
            if isinstance(capability.get("Headers"), Mapping)
            else {}
        )

        headers: dict[str, str] = {}
        for source in (default_headers, capability_headers):
            for raw_key, raw_value in source.items():
                key = str(raw_key or "").strip()
                if key == "":
                    continue
                value = str(raw_value)
                value = value.replace("{secret}", secret_text)
                value = value.replace("{secret_ref}", str(instance.secret_ref or ""))
                headers[key] = value

        if not any(header.casefold() == "authorization" for header in headers):
            auth_scheme = self._normalize_optional_text(capability.get("AuthScheme"))
            if auth_scheme is None:
                auth_scheme = "Bearer"
            if auth_scheme:
                headers["Authorization"] = f"{auth_scheme} {secret_text}"
            else:
                headers["Authorization"] = secret_text

        return headers

    def _invoke_request_spec(
        self,
        *,
        base_url: str,
        capability: Mapping[str, Any],
        input_json: Any,
    ) -> tuple[str, str, dict[str, str], dict[str, Any], str | None, Any | None]:
        method = self._normalize_optional_text(capability.get("Method")) or "POST"
        method = method.upper()

        path_template = self._normalize_optional_text(capability.get("PathTemplate"))
        if path_template is None:
            abort(409, "Capability.PathTemplate must be configured.")

        if not path_template.startswith("/"):
            abort(409, "Capability.PathTemplate must start with '/'.")

        format_values: dict[str, Any] = {}
        if isinstance(input_json, Mapping):
            format_values = {str(k): self._json_safe(v) for k, v in input_json.items()}
        path = path_template.format_map(_SafeFormatDict(format_values))

        placement = self._normalize_optional_text(capability.get("InputPlacement"))
        placement = (placement or "json").casefold()

        query_params: dict[str, str] = {}
        body_text: str | None = None
        body_json: Any | None = None

        if placement == "query":
            if isinstance(input_json, Mapping):
                for key, value in input_json.items():
                    query_params[str(key)] = json.dumps(
                        self._json_safe(value),
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
            else:
                query_params["input"] = json.dumps(
                    self._json_safe(input_json),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
        elif placement in {"body", "text"}:
            body_text = json.dumps(
                self._json_safe(input_json),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        else:
            body_json = self._json_safe(input_json)

        return (
            method,
            f"{base_url}{path}",
            query_params,
            {},
            body_text,
            body_json,
        )

    @staticmethod
    def _response_payload(content_type: str | None, text_body: str) -> Any:
        content_type_text = str(content_type or "").casefold()
        if "json" in content_type_text:
            try:
                return json.loads(text_body)
            except json.JSONDecodeError:
                return {
                    "Text": text_body,
                    "ParseError": (
                        "response content-type indicated json but decoding failed"
                    ),
                }
        return {"Text": text_body}

    async def _execute_http_request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None,
        body_text: str | None,
        body_json: Any,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        retry_status_codes: tuple[int, ...],
    ) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        attempts_allowed = max(0, int(max_retries)) + 1

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, attempts_allowed + 1):
                try:
                    async with session.request(
                        method,
                        url,
                        headers=dict(headers),
                        params=dict(params or {}),
                        data=body_text,
                        json=body_json,
                    ) as response:
                        response_text = await response.text()
                        payload = self._response_payload(
                            response.headers.get("Content-Type"),
                            response_text,
                        )
                        status_code = int(response.status)

                        if (
                            status_code in retry_status_codes
                            and attempt < attempts_allowed
                        ):
                            await asyncio.sleep(
                                float(retry_backoff_seconds) * (2 ** (attempt - 1))
                            )
                            continue

                        return {
                            "ok": 200 <= status_code < 400,
                            "status_code": status_code,
                            "payload": payload,
                            "attempt_count": attempt,
                            "timeout": False,
                            "transport_error": None,
                        }
                except asyncio.TimeoutError:
                    if attempt < attempts_allowed:
                        await asyncio.sleep(
                            float(retry_backoff_seconds) * (2 ** (attempt - 1))
                        )
                        continue

                    return {
                        "ok": False,
                        "status_code": 504,
                        "payload": None,
                        "attempt_count": attempt,
                        "timeout": True,
                        "transport_error": "request timeout",
                    }
                except aiohttp.ClientError as exc:
                    if attempt < attempts_allowed:
                        await asyncio.sleep(
                            float(retry_backoff_seconds) * (2 ** (attempt - 1))
                        )
                        continue

                    return {
                        "ok": False,
                        "status_code": 502,
                        "payload": None,
                        "attempt_count": attempt,
                        "timeout": False,
                        "transport_error": str(exc),
                    }

        return {
            "ok": False,
            "status_code": 502,
            "payload": None,
            "attempt_count": attempts_allowed,
            "timeout": False,
            "transport_error": "request execution did not return a response",
        }

    async def _persist_call_log(
        self,
        *,
        tenant_id: uuid.UUID,
        trace_id: str,
        connector_instance_id: uuid.UUID,
        capability_name: str,
        client_action_key: str | None,
        request_json: Any,
        request_hash: str,
        response_json: Any,
        response_hash: str | None,
        status: str,
        http_status_code: int | None,
        attempt_count: int,
        duration_ms: int,
        error_json: Any,
        escalation_json: Any,
        auth_user_id: uuid.UUID,
    ) -> uuid.UUID:
        created = await self._call_log_service.create(
            {
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "connector_instance_id": connector_instance_id,
                "capability_name": capability_name,
                "client_action_key": client_action_key,
                "request_json": request_json,
                "request_hash": request_hash,
                "response_json": response_json,
                "response_hash": response_hash,
                "status": status,
                "http_status_code": http_status_code,
                "attempt_count": attempt_count,
                "duration_ms": max(0, int(duration_ms)),
                "error_json": error_json,
                "escalation_json": escalation_json,
                "invoked_by_user_id": auth_user_id,
                "invoked_at": self._now_utc(),
            }
        )
        if created.id is None:
            abort(500, "Connector call log ID was not generated.")
        return created.id

    async def _run_failure_escalation(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        escalation_policy_key: str | None,
        trace_id: str,
        connector_instance_id: uuid.UUID,
        capability_name: str,
        request_hash: str,
        http_status_code: int | None,
        error_json: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        policy_key = self._normalize_optional_text(escalation_policy_key)
        if policy_key is None:
            return None

        payload = {
            "EventType": "connector.call_failed",
            "TraceId": trace_id,
            "ConnectorInstanceId": str(connector_instance_id),
            "CapabilityName": capability_name,
            "RequestHash": request_hash,
            "HttpStatusCode": http_status_code,
            "Error": self._json_safe(error_json),
        }

        try:
            result, status = await self._sla_escalation_policy_service.action_execute(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=auth_user_id,
                data=SlaEscalationExecuteValidation(
                    policy_key=policy_key,
                    trigger_event_json=payload,
                    dry_run=False,
                ),
            )
            return {
                "Attempted": True,
                "StatusCode": int(status),
                "Result": self._json_safe(result),
            }
        except HTTPException as exc:
            return {
                "Attempted": True,
                "Error": {
                    "Code": int(exc.code or 500),
                    "Description": str(exc.description),
                },
            }
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "Attempted": True,
                "Error": {
                    "Code": "error",
                    "Description": str(exc),
                },
            }

    async def _acquire_dedup(
        self,
        *,
        tenant_id: uuid.UUID,
        instance_id: uuid.UUID,
        capability_name: str,
        client_action_key: str | None,
        request_hash: str,
    ) -> dict[str, Any]:
        key = self._normalize_optional_text(client_action_key)
        if key is None:
            return {
                "enabled": False,
                "record_id": None,
                "replay": None,
            }

        scope = f"ops_connector.invoke:{instance_id}:{capability_name.casefold()}"
        try:
            existing = await self._dedup_service.get(
                {
                    "tenant_id": tenant_id,
                    "scope": scope,
                    "idempotency_key": key,
                }
            )
        except SQLAlchemyError:
            abort(500)

        if existing is not None:
            existing_hash = self._normalize_optional_text(existing.request_hash)
            if existing_hash is not None and existing_hash != request_hash:
                abort(409, "ClientActionKey request hash mismatch.")

        acquired = await self._dedup_service.acquire(
            tenant_id=tenant_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            owner_instance="ops_connector.invoke",
        )
        decision = str(acquired.get("decision") or "").strip().lower()
        record = acquired.get("record")
        record_id = getattr(record, "id", None)

        if decision == "conflict":
            abort(409, "ClientActionKey request hash mismatch.")
        if decision == "in_progress":
            abort(409, "ClientActionKey is currently in progress.")

        if decision == "replay":
            payload = acquired.get("response_payload")
            code = int(acquired.get("response_code") or 200)
            if isinstance(payload, Mapping):
                replay_payload = dict(payload)
                replay_payload["Idempotent"] = True
            else:
                replay_payload = payload

            return {
                "enabled": True,
                "record_id": record_id,
                "replay": (replay_payload, code),
            }

        return {
            "enabled": True,
            "record_id": record_id,
            "replay": None,
        }

    async def _commit_dedup_success(
        self,
        *,
        state: Mapping[str, Any],
        response_code: int,
        response_payload: Any,
    ) -> None:
        if not bool(state.get("enabled")):
            return

        record_id = state.get("record_id")
        if not isinstance(record_id, uuid.UUID):
            return

        try:
            await self._dedup_service.commit_success(
                entity_id=record_id,
                response_code=response_code,
                response_payload=response_payload,
                result_ref=None,
            )
        except HTTPException:
            return

    async def _commit_dedup_failure(
        self,
        *,
        state: Mapping[str, Any],
        response_code: int,
        response_payload: Any,
        error_code: str,
        error_message: str,
    ) -> None:
        if not bool(state.get("enabled")):
            return

        record_id = state.get("record_id")
        if not isinstance(record_id, uuid.UUID):
            return

        try:
            await self._dedup_service.commit_failure(
                entity_id=record_id,
                response_code=response_code,
                response_payload=response_payload,
                error_code=error_code,
                error_message=error_message,
            )
        except HTTPException:
            return

    async def create(self, values: Mapping[str, Any]) -> ConnectorInstanceDE:
        payload = dict(values)

        try:
            validated = ConnectorInstanceCreateValidation.model_validate(payload)
        except Exception as exc:  # pylint: disable=broad-except
            abort(400, str(exc))

        payload["connector_type_id"] = await self._resolve_connector_type_id_for_create(
            connector_type_id=validated.connector_type_id,
            connector_type_key=validated.connector_type_key,
        )
        payload.pop("connector_type_key", None)

        payload["display_name"] = str(validated.display_name)
        payload["config_json"] = dict(validated.config_json)
        payload["secret_ref"] = str(validated.secret_ref)
        payload["status"] = str(validated.status or "active")
        payload["escalation_policy_key"] = validated.escalation_policy_key
        payload["retry_policy_json"] = (
            dict(validated.retry_policy_json)
            if validated.retry_policy_json is not None
            else None
        )

        return await super().create(payload)

    async def action_test_connection(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ConnectorInstanceTestConnectionValidation,
    ) -> tuple[dict[str, Any], int]:
        _ = entity_id

        started_at = self._now_utc()
        trace_id = self._normalize_optional_text(data.trace_id) or uuid.uuid4().hex

        current = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )

        if current.id is None:
            abort(409, "Connector instance identifier is missing.")

        if self._normalize_status(current.status) != "active":
            abort(409, "Connector instance is not active.")

        connector_type = await self._resolve_connector_type(
            connector_type_id=current.connector_type_id,
        )
        if str(connector_type.adapter_kind or "").casefold() != "http_json":
            abort(409, "Only http_json adapter_kind is supported in Phase 6.")

        secret = await self._resolve_secret_material(
            tenant_id=tenant_id,
            secret_ref=str(current.secret_ref),
        )

        base_url = self._resolve_base_url(current)
        config_json = (
            current.config_json if isinstance(current.config_json, Mapping) else {}
        )
        health_path = (
            self._normalize_optional_text(config_json.get("HealthPath")) or "/"
        )
        if not health_path.startswith("/"):
            health_path = "/" + health_path

        timeout_seconds, _max_retries, _backoff, _retry_codes = (
            self._resolve_retry_policy(
                instance=current,
                capability={},
            )
        )

        headers = self._resolve_headers(
            instance=current,
            capability={
                "AuthScheme": "Bearer",
                "Headers": (
                    config_json.get("HealthHeaders")
                    if isinstance(config_json.get("HealthHeaders"), Mapping)
                    else {}
                ),
            },
            secret_text=secret.secret.decode("utf-8", errors="ignore"),
        )

        request_json = {
            "Method": "GET",
            "Url": f"{base_url}{health_path}",
        }

        execution = await self._execute_http_request(
            method="GET",
            url=f"{base_url}{health_path}",
            headers=headers,
            params=None,
            body_text=None,
            body_json=None,
            timeout_seconds=timeout_seconds,
            max_retries=0,
            retry_backoff_seconds=0.0,
            retry_status_codes=(),
        )

        finished_at = self._now_utc()
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

        cfg = self._connector_config()
        redacted_request = self._redact_payload(
            request_json, redacted_keys=cfg.redacted_keys
        )
        redacted_response = self._redact_payload(
            execution.get("payload"),
            redacted_keys=cfg.redacted_keys,
        )

        request_hash = self._sha256_hex(redacted_request)
        response_hash = (
            self._sha256_hex(redacted_response)
            if redacted_response is not None
            else None
        )

        error_json = None
        if not bool(execution.get("ok")):
            error_json = {
                "Code": "health_check_failed",
                "Timeout": bool(execution.get("timeout")),
                "TransportError": self._normalize_optional_text(
                    execution.get("transport_error")
                ),
            }

        call_log_id = await self._persist_call_log(
            tenant_id=tenant_id,
            trace_id=trace_id,
            connector_instance_id=current.id,
            capability_name="__test_connection__",
            client_action_key=None,
            request_json=redacted_request,
            request_hash=request_hash,
            response_json=redacted_response,
            response_hash=response_hash,
            status="ok" if bool(execution.get("ok")) else "failed",
            http_status_code=int(execution.get("status_code") or 0) or None,
            attempt_count=int(execution.get("attempt_count") or 1),
            duration_ms=duration_ms,
            error_json=error_json,
            escalation_json=None,
            auth_user_id=auth_user_id,
        )

        return (
            {
                "Ok": bool(execution.get("ok")),
                "StatusCode": int(execution.get("status_code") or 0),
                "LatencyMs": duration_ms,
                "ConnectorCallLogId": str(call_log_id),
                "Details": self._json_safe(execution.get("payload")),
            },
            200,
        )

    async def action_invoke(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ConnectorInstanceInvokeValidation,
    ) -> tuple[dict[str, Any], int]:
        started_at = self._now_utc()
        trace_id = self._normalize_optional_text(data.trace_id) or uuid.uuid4().hex

        await self._emit_connector_biz_trace(
            stage="start",
            tenant_id=tenant_id,
            action_name="invoke",
            trace_id=trace_id,
            status_code=None,
            duration_ms=None,
            details={
                "Operation": "invoke",
                "EntityId": str(entity_id),
                "CapabilityName": data.capability_name,
            },
        )

        current = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )

        if current.id is None:
            abort(409, "Connector instance identifier is missing.")

        if self._normalize_status(current.status) != "active":
            abort(409, "Connector instance is not active.")

        connector_type = await self._resolve_connector_type(
            connector_type_id=current.connector_type_id,
        )
        if str(connector_type.adapter_kind or "").casefold() != "http_json":
            abort(409, "Only http_json adapter_kind is supported in Phase 6.")

        configured_capability_name, capability = self._resolve_capability(
            connector_type=connector_type,
            capability_name=data.capability_name,
        )

        cfg = self._connector_config()
        redacted_input = self._redact_payload(
            self._json_safe(data.input_json),
            redacted_keys=cfg.redacted_keys,
        )
        request_hash = self._sha256_hex(redacted_input)

        dedup_state = await self._acquire_dedup(
            tenant_id=tenant_id,
            instance_id=current.id,
            capability_name=configured_capability_name,
            client_action_key=data.client_action_key,
            request_hash=request_hash,
        )
        replay = dedup_state.get("replay")
        if isinstance(replay, tuple) and len(replay) == 2:
            payload = replay[0]
            code = int(replay[1])
            return payload, code

        input_schema_ref = self._schema_ref(capability, "InputSchema")
        await self._validate_input_schema(
            tenant_id=tenant_id,
            schema_ref=input_schema_ref,
            payload=data.input_json,
        )

        output_schema_ref = self._schema_ref(capability, "OutputSchema")

        secret = await self._resolve_secret_material(
            tenant_id=tenant_id,
            secret_ref=str(current.secret_ref),
        )
        secret_text = secret.secret.decode("utf-8", errors="ignore")

        base_url = self._resolve_base_url(current)
        timeout_seconds, max_retries, retry_backoff_seconds, retry_status_codes = (
            self._resolve_retry_policy(instance=current, capability=capability)
        )

        method, url, params, _unused, body_text, body_json = self._invoke_request_spec(
            base_url=base_url,
            capability=capability,
            input_json=data.input_json,
        )

        headers = self._resolve_headers(
            instance=current,
            capability=capability,
            secret_text=secret_text,
        )

        execution = await self._execute_http_request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            body_text=body_text,
            body_json=body_json,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            retry_status_codes=retry_status_codes,
        )

        finished_at = self._now_utc()
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        http_status_code = int(execution.get("status_code") or 0)
        attempt_count = int(execution.get("attempt_count") or 1)

        redacted_request = self._redact_payload(
            {
                "Method": method,
                "Url": url,
                "Params": params,
                "Headers": headers,
                "InputPlacement": self._normalize_optional_text(
                    capability.get("InputPlacement")
                )
                or "json",
                "InputJson": data.input_json,
            },
            redacted_keys=cfg.redacted_keys,
        )
        redacted_response = self._redact_payload(
            self._json_safe(execution.get("payload")),
            redacted_keys=cfg.redacted_keys,
        )
        response_hash = (
            self._sha256_hex(redacted_response)
            if redacted_response is not None
            else None
        )

        if bool(execution.get("ok")):
            output_errors = await self._validate_output_schema(
                tenant_id=tenant_id,
                schema_ref=output_schema_ref,
                payload=execution.get("payload"),
            )
            if output_errors:
                error_json = {
                    "Code": "output_schema_invalid",
                    "Errors": output_errors,
                }
                escalation_json = await self._run_failure_escalation(
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    escalation_policy_key=current.escalation_policy_key,
                    trace_id=trace_id,
                    connector_instance_id=current.id,
                    capability_name=configured_capability_name,
                    request_hash=request_hash,
                    http_status_code=http_status_code,
                    error_json=error_json,
                )

                call_log_id = await self._persist_call_log(
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    connector_instance_id=current.id,
                    capability_name=configured_capability_name,
                    client_action_key=self._normalize_optional_text(
                        data.client_action_key
                    ),
                    request_json=redacted_request,
                    request_hash=request_hash,
                    response_json=redacted_response,
                    response_hash=response_hash,
                    status="failed",
                    http_status_code=http_status_code,
                    attempt_count=attempt_count,
                    duration_ms=duration_ms,
                    error_json=error_json,
                    escalation_json=escalation_json,
                    auth_user_id=auth_user_id,
                )

                response_payload = {
                    "ConnectorCallLogId": str(call_log_id),
                    "TraceId": trace_id,
                    "CapabilityName": configured_capability_name,
                    "Status": "failed",
                    "HttpStatusCode": http_status_code,
                    "AttemptCount": attempt_count,
                    "OutputJson": self._json_safe(execution.get("payload")),
                    "Idempotent": False,
                }

                await self._commit_dedup_failure(
                    state=dedup_state,
                    response_code=502,
                    response_payload=response_payload,
                    error_code="output_schema_invalid",
                    error_message="; ".join(output_errors),
                )

                await self._emit_connector_biz_trace(
                    stage="error",
                    tenant_id=tenant_id,
                    action_name="invoke",
                    trace_id=trace_id,
                    status_code=502,
                    duration_ms=duration_ms,
                    details={
                        "Operation": "invoke",
                        "CapabilityName": configured_capability_name,
                        "ErrorCode": "output_schema_invalid",
                    },
                )

                return response_payload, 502

            call_log_id = await self._persist_call_log(
                tenant_id=tenant_id,
                trace_id=trace_id,
                connector_instance_id=current.id,
                capability_name=configured_capability_name,
                client_action_key=self._normalize_optional_text(data.client_action_key),
                request_json=redacted_request,
                request_hash=request_hash,
                response_json=redacted_response,
                response_hash=response_hash,
                status="ok",
                http_status_code=http_status_code,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                error_json=None,
                escalation_json=None,
                auth_user_id=auth_user_id,
            )

            response_payload = {
                "ConnectorCallLogId": str(call_log_id),
                "TraceId": trace_id,
                "CapabilityName": configured_capability_name,
                "Status": "ok",
                "HttpStatusCode": http_status_code,
                "AttemptCount": attempt_count,
                "OutputJson": self._json_safe(execution.get("payload")),
                "Idempotent": False,
            }

            await self._commit_dedup_success(
                state=dedup_state,
                response_code=200,
                response_payload=response_payload,
            )

            await self._emit_connector_biz_trace(
                stage="finish",
                tenant_id=tenant_id,
                action_name="invoke",
                trace_id=trace_id,
                status_code=200,
                duration_ms=duration_ms,
                details={
                    "Operation": "invoke",
                    "CapabilityName": configured_capability_name,
                    "AttemptCount": attempt_count,
                },
            )

            return response_payload, 200

        gateway_code = 504 if bool(execution.get("timeout")) else 502
        error_json = {
            "Code": "connector_invoke_failed",
            "Timeout": bool(execution.get("timeout")),
            "TransportError": self._normalize_optional_text(
                execution.get("transport_error")
            ),
            "HttpStatusCode": http_status_code,
        }

        escalation_json = await self._run_failure_escalation(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            escalation_policy_key=current.escalation_policy_key,
            trace_id=trace_id,
            connector_instance_id=current.id,
            capability_name=configured_capability_name,
            request_hash=request_hash,
            http_status_code=http_status_code,
            error_json=error_json,
        )

        call_log_id = await self._persist_call_log(
            tenant_id=tenant_id,
            trace_id=trace_id,
            connector_instance_id=current.id,
            capability_name=configured_capability_name,
            client_action_key=self._normalize_optional_text(data.client_action_key),
            request_json=redacted_request,
            request_hash=request_hash,
            response_json=redacted_response,
            response_hash=response_hash,
            status="failed",
            http_status_code=http_status_code,
            attempt_count=attempt_count,
            duration_ms=duration_ms,
            error_json=error_json,
            escalation_json=escalation_json,
            auth_user_id=auth_user_id,
        )

        response_payload = {
            "ConnectorCallLogId": str(call_log_id),
            "TraceId": trace_id,
            "CapabilityName": configured_capability_name,
            "Status": "failed",
            "HttpStatusCode": http_status_code,
            "AttemptCount": attempt_count,
            "OutputJson": self._json_safe(execution.get("payload")),
            "Idempotent": False,
        }

        await self._commit_dedup_failure(
            state=dedup_state,
            response_code=gateway_code,
            response_payload=response_payload,
            error_code="connector_invoke_failed",
            error_message=(
                self._normalize_optional_text(execution.get("transport_error"))
                or "Connector invoke failed."
            ),
        )

        await self._emit_connector_biz_trace(
            stage="error",
            tenant_id=tenant_id,
            action_name="invoke",
            trace_id=trace_id,
            status_code=gateway_code,
            duration_ms=duration_ms,
            details={
                "Operation": "invoke",
                "CapabilityName": configured_capability_name,
                "AttemptCount": attempt_count,
                "Timeout": bool(execution.get("timeout")),
            },
        )

        return response_payload, gateway_code
