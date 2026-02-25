"""JSON schema helpers used by ACP schema registry services."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a value into canonical UTF-8 JSON bytes."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def checksum_sha256(value: Any) -> str:
    """Compute SHA-256 hex digest of a JSON-serializable value."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()  # noqa: S324


def json_size_bytes(value: Any) -> int:
    """Return canonical JSON byte size for a JSON-serializable value."""
    return len(canonical_json_bytes(value))


def validate_json_schema_payload(
    *,
    schema: Mapping[str, Any],
    payload: Any,
) -> list[str]:
    """Validate payload against a constrained JSON-schema subset."""
    errors: list[str] = []
    _validate_node(schema=schema, value=payload, path="$", errors=errors)
    return errors


def _validate_node(
    *,
    schema: Mapping[str, Any],
    value: Any,
    path: str,
    errors: list[str],
) -> None:
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(expected_type, value):
        errors.append(
            f"{path}: expected type {expected_type!r}, got {type(value).__name__!r}."
        )
        return

    if _contains_type(expected_type, "object"):
        if not isinstance(value, Mapping):
            return

        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            errors.append(f"{path}: schema.properties must be an object.")
            return

        required = schema.get("required", [])
        if isinstance(required, list):
            for required_key in required:
                if str(required_key) not in value:
                    errors.append(f"{path}.{required_key}: required property missing.")

        additional_properties = schema.get("additionalProperties", True)
        for key, child_value in value.items():
            child_schema = properties.get(str(key))
            child_path = f"{path}.{key}"
            if isinstance(child_schema, Mapping):
                _validate_node(
                    schema=child_schema,
                    value=child_value,
                    path=child_path,
                    errors=errors,
                )
                continue

            if additional_properties is False:
                errors.append(f"{child_path}: additional property is not allowed.")

    if _contains_type(expected_type, "array"):
        if not isinstance(value, list):
            return

        item_schema = schema.get("items")
        if not isinstance(item_schema, Mapping):
            return

        for idx, item in enumerate(value):
            _validate_node(
                schema=item_schema,
                value=item,
                path=f"{path}[{idx}]",
                errors=errors,
            )


def apply_json_schema_defaults(*, schema: Mapping[str, Any], payload: Any) -> Any:
    """Apply schema defaults to payload recursively without type coercion."""
    return _apply_defaults(schema=schema, value=payload)


def _apply_defaults(*, schema: Mapping[str, Any], value: Any) -> Any:
    expected_type = schema.get("type")

    if _contains_type(expected_type, "object") and isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return dict(value)

        result: dict[str, Any] = {str(k): copy.deepcopy(v) for k, v in value.items()}

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, Mapping):
                continue

            key = str(prop_name)
            if key in result:
                result[key] = _apply_defaults(schema=prop_schema, value=result[key])
                continue

            if "default" in prop_schema:
                result[key] = copy.deepcopy(prop_schema["default"])

        return result

    if _contains_type(expected_type, "array") and isinstance(value, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, Mapping):
            return list(value)
        return [_apply_defaults(schema=item_schema, value=item) for item in value]

    return copy.deepcopy(value)


def _contains_type(raw_type: Any, expected: str) -> bool:
    if isinstance(raw_type, str):
        return raw_type == expected

    if isinstance(raw_type, list):
        return any(str(item) == expected for item in raw_type)

    return False


def _matches_type(expected_type: Any, value: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(item, value) for item in expected_type)

    if not isinstance(expected_type, str):
        return True

    match expected_type:
        case "object":
            return isinstance(value, Mapping)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return (
                isinstance(value, int) or isinstance(value, float)
            ) and not isinstance(
                value,
                bool,
            )
        case "boolean":
            return isinstance(value, bool)
        case "null":
            return value is None
        case _:
            return True
