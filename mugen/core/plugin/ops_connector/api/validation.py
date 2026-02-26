"""Validation schemas used by ops_connector ACP resources and actions."""

from __future__ import annotations

from typing import Any, Literal
import uuid

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _validate_schema_ref(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object when provided.")

    schema_definition_id = value.get("SchemaDefinitionId")
    key = _normalize_optional_text(value.get("Key"))
    version = value.get("Version")

    if schema_definition_id is not None:
        try:
            uuid.UUID(str(schema_definition_id))
        except ValueError as exc:
            raise ValueError(
                f"{field_name}.SchemaDefinitionId must be a UUID."
            ) from exc
        return

    if key is None:
        raise ValueError(
            f"{field_name} must include SchemaDefinitionId or Key + Version."
        )
    try:
        parsed_version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}.Version must be a positive integer.") from exc
    if parsed_version <= 0:
        raise ValueError(f"{field_name}.Version must be a positive integer.")


class ConnectorTypeCreateValidation(IValidationBase):
    """Validate generic create inputs for ConnectorType."""

    key: str
    display_name: str
    adapter_kind: str = "http_json"
    capabilities_json: Any = Field(default_factory=dict)
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ConnectorTypeCreateValidation":
        self.key = self.key.strip()
        if self.key == "":
            raise ValueError("Key must be non-empty.")

        self.display_name = self.display_name.strip()
        if self.display_name == "":
            raise ValueError("DisplayName must be non-empty.")

        self.adapter_kind = self.adapter_kind.strip().lower()
        if self.adapter_kind != "http_json":
            raise ValueError("AdapterKind must be http_json.")

        if not isinstance(self.capabilities_json, dict):
            raise ValueError("CapabilitiesJson must be an object.")

        for cap_name, definition in self.capabilities_json.items():
            if not str(cap_name or "").strip():
                raise ValueError("CapabilitiesJson keys must be non-empty.")
            if not isinstance(definition, dict):
                raise ValueError(
                    "Each capability definition in CapabilitiesJson must be an object."
                )

            method = _normalize_optional_text(definition.get("Method"))
            if method is not None:
                definition["Method"] = method.upper()

            path_template = _normalize_optional_text(definition.get("PathTemplate"))
            if path_template is not None and not path_template.startswith("/"):
                raise ValueError(
                    f"CapabilitiesJson[{cap_name}].PathTemplate must start with '/'."
                )

            headers = definition.get("Headers")
            if headers is not None and not isinstance(headers, dict):
                raise ValueError(
                    f"CapabilitiesJson[{cap_name}].Headers must be an object."
                )

            retry_status_codes = definition.get("RetryStatusCodes")
            if retry_status_codes is not None:
                if not isinstance(retry_status_codes, list) or not retry_status_codes:
                    raise ValueError(
                        (
                            "CapabilitiesJson"
                            f"[{cap_name}].RetryStatusCodes must be a non-empty array."
                        )
                    )
                for code in retry_status_codes:
                    try:
                        parsed = int(code)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            (
                                "CapabilitiesJson"
                                f"[{cap_name}].RetryStatusCodes must contain integers."
                            )
                        ) from exc
                    if parsed < 100 or parsed > 599:
                        raise ValueError(
                            (
                                "CapabilitiesJson"
                                f"[{cap_name}].RetryStatusCodes must be "
                                "HTTP status codes."
                            )
                        )

            _validate_schema_ref(
                definition.get("InputSchema"),
                field_name=f"CapabilitiesJson[{cap_name}].InputSchema",
            )
            _validate_schema_ref(
                definition.get("OutputSchema"),
                field_name=f"CapabilitiesJson[{cap_name}].OutputSchema",
            )

        return self


class ConnectorInstanceCreateValidation(IValidationBase):
    """Validate generic create inputs for ConnectorInstance."""

    tenant_id: uuid.UUID | None = None
    connector_type_id: uuid.UUID | None = None
    connector_type_key: str | None = None
    display_name: str
    config_json: Any = Field(default_factory=dict)
    secret_ref: str
    status: Literal["active", "disabled", "error"] | None = None
    escalation_policy_key: str | None = None
    retry_policy_json: Any | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ConnectorInstanceCreateValidation":
        if (
            self.connector_type_id is None
            and not (self.connector_type_key or "").strip()
        ):
            raise ValueError("ConnectorTypeId or ConnectorTypeKey is required.")

        if self.connector_type_key is not None:
            self.connector_type_key = self.connector_type_key.strip()
            if self.connector_type_key == "":
                raise ValueError("ConnectorTypeKey cannot be empty when provided.")

        self.display_name = self.display_name.strip()
        if self.display_name == "":
            raise ValueError("DisplayName must be non-empty.")

        self.secret_ref = self.secret_ref.strip()
        if self.secret_ref == "":
            raise ValueError("SecretRef must be non-empty.")

        if not isinstance(self.config_json, dict):
            raise ValueError("ConfigJson must be an object.")

        if self.retry_policy_json is not None and not isinstance(
            self.retry_policy_json, dict
        ):
            raise ValueError("RetryPolicyJson must be an object when provided.")

        self.escalation_policy_key = _normalize_optional_text(
            self.escalation_policy_key
        )

        return self


class ConnectorInstanceTestConnectionValidation(IValidationBase):
    """Validate payload for test_connection actions."""

    row_version: NonNegativeInt
    trace_id: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ConnectorInstanceTestConnectionValidation":
        self.trace_id = _normalize_optional_text(self.trace_id)
        return self


class ConnectorInstanceInvokeValidation(IValidationBase):
    """Validate payload for invoke actions."""

    row_version: NonNegativeInt
    capability_name: str
    input_json: Any
    trace_id: str | None = None
    client_action_key: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ConnectorInstanceInvokeValidation":
        self.capability_name = self.capability_name.strip()
        if self.capability_name == "":
            raise ValueError("CapabilityName must be non-empty.")

        self.trace_id = _normalize_optional_text(self.trace_id)
        self.client_action_key = _normalize_optional_text(self.client_action_key)

        return self


class ConnectorRetryPolicyValidation(IValidationBase):
    """Validate explicit retry policy objects used in tests/fixtures."""

    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: NonNegativeInt | None = None
    retry_backoff_seconds: float | None = Field(default=None, ge=0)
    retry_status_codes: list[int] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ConnectorRetryPolicyValidation":
        if self.retry_status_codes is not None:
            if not self.retry_status_codes:
                raise ValueError("RetryStatusCodes cannot be empty when provided.")
            for code in self.retry_status_codes:
                if code < 100 or code > 599:
                    raise ValueError(
                        "RetryStatusCodes must contain valid HTTP status codes."
                    )
        return self
