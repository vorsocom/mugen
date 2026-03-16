"""Tests for ACP schema JSON helper utilities."""

from pathlib import Path
from types import ModuleType
import sys
import unittest


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


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.utility import schema_json as schema_json_mod
from mugen.core.plugin.acp.utility.schema_json import (
    apply_json_schema_defaults,
    checksum_sha256,
    json_size_bytes,
    validate_json_schema_payload,
)


class TestMugenAcpUtilitySchemaJson(unittest.TestCase):
    """Covers canonical hashing, validation, and default coercion helpers."""

    def test_checksum_is_canonical_for_key_order(self) -> None:
        left = {"b": 2, "a": 1}
        right = {"a": 1, "b": 2}

        self.assertEqual(checksum_sha256(left), checksum_sha256(right))
        self.assertGreater(json_size_bytes(left), 0)

    def test_validate_json_schema_payload_object_rules(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "Name": {"type": "string"},
                "Count": {"type": "integer"},
            },
            "required": ["Name"],
            "additionalProperties": False,
        }

        valid_errors = validate_json_schema_payload(
            schema=schema,
            payload={"Name": "ok", "Count": 1},
        )
        self.assertEqual(valid_errors, [])

        missing_required = validate_json_schema_payload(
            schema=schema,
            payload={"Count": 1},
        )
        self.assertTrue(
            any("required property missing" in item for item in missing_required)
        )

        unknown_errors = validate_json_schema_payload(
            schema=schema,
            payload={"Name": "ok", "Extra": True},
        )
        self.assertTrue(
            any("additional property is not allowed" in item for item in unknown_errors)
        )

        type_mismatch = validate_json_schema_payload(
            schema={"type": "string"},
            payload=123,
        )
        self.assertTrue(any("expected type" in item for item in type_mismatch))

        bad_properties = validate_json_schema_payload(
            schema={"type": "object", "properties": "bad"},
            payload={"Name": "ok"},
        )
        self.assertTrue(
            any(
                "schema.properties must be an object" in item for item in bad_properties
            )
        )

        no_object_walk = validate_json_schema_payload(
            schema={"type": ["object", "string"]},
            payload="not-an-object",
        )
        self.assertEqual(no_object_walk, [])

        no_array_walk = validate_json_schema_payload(
            schema={"type": ["array", "string"], "items": {"type": "string"}},
            payload="not-an-array",
        )
        self.assertEqual(no_array_walk, [])

        no_item_schema = validate_json_schema_payload(
            schema={"type": "array", "items": "bad"},
            payload=["x"],
        )
        self.assertEqual(no_item_schema, [])

        array_errors = validate_json_schema_payload(
            schema={"type": "array", "items": {"type": "integer"}},
            payload=[1, "bad"],
        )
        self.assertTrue(any("$[1]" in item for item in array_errors))

        no_required_walk = validate_json_schema_payload(
            schema={
                "type": "object",
                "required": "Name",
                "properties": {},
            },
            payload={},
        )
        self.assertEqual(no_required_walk, [])

        additional_allowed = validate_json_schema_payload(
            schema={
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            },
            payload={"x": 1},
        )
        self.assertEqual(additional_allowed, [])

    def test_apply_defaults_recursively_without_type_casting(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "Name": {"type": "string", "default": "fallback"},
                "Flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"Enabled": {"type": "boolean", "default": True}},
                    },
                },
            },
        }

        output = apply_json_schema_defaults(
            schema=schema,
            payload={"Flags": [{}]},
        )
        self.assertEqual(output["Name"], "fallback")
        self.assertEqual(output["Flags"][0]["Enabled"], True)

        passthrough = apply_json_schema_defaults(
            schema={"type": "object", "properties": "bad"},
            payload={"x": 1},
        )
        self.assertEqual(passthrough, {"x": 1})

        non_mapping_prop_schema = apply_json_schema_defaults(
            schema={
                "type": "object",
                "properties": {"Name": "bad"},
            },
            payload={},
        )
        self.assertEqual(non_mapping_prop_schema, {})

        list_passthrough = apply_json_schema_defaults(
            schema={"type": "array", "items": "bad"},
            payload=[{"x": 1}],
        )
        self.assertEqual(list_passthrough, [{"x": 1}])

        no_default_schema = apply_json_schema_defaults(
            schema={
                "type": "object",
                "properties": {"Name": {"type": "string"}},
            },
            payload={},
        )
        self.assertEqual(no_default_schema, {})

        primitive_copy = apply_json_schema_defaults(
            schema={"type": "string"},
            payload="x",
        )
        self.assertEqual(primitive_copy, "x")

    def test_private_type_helpers_cover_all_supported_types(self) -> None:
        self.assertTrue(
            schema_json_mod._contains_type("object", "object")
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._contains_type(["null", "string"], "string")
        )  # pylint: disable=protected-access
        self.assertFalse(
            schema_json_mod._contains_type(None, "string")
        )  # pylint: disable=protected-access

        self.assertTrue(
            schema_json_mod._matches_type(["null", "string"], "x")
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type({"unexpected": True}, "x")
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("object", {"a": 1})
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("array", [1])
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("string", "x")
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("integer", 1)
        )  # pylint: disable=protected-access
        self.assertFalse(
            schema_json_mod._matches_type("integer", True)
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("number", 1.5)
        )  # pylint: disable=protected-access
        self.assertFalse(
            schema_json_mod._matches_type("number", True)
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("boolean", False)
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("null", None)
        )  # pylint: disable=protected-access
        self.assertTrue(
            schema_json_mod._matches_type("custom-type", object())
        )  # pylint: disable=protected-access
