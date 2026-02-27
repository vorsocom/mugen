"""Unit tests for mugen.core.utility.collection.namespace."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mugen.core.utility.collection.namespace import (
    NamespaceConfig,
    nested_namespace_from_dict,
    to_namespace,
)


class TestMugenUtilityCollectionNamespace(unittest.TestCase):
    """Covers namespace conversion edge cases and collision policies."""

    def test_to_namespace_none_and_passthrough_namespace(self) -> None:
        ns = SimpleNamespace(value=1)
        self.assertIsNone(to_namespace(None))
        self.assertIs(to_namespace(ns), ns)

    def test_to_namespace_builds_aliases_and_internal_maps(self) -> None:
        payload = {"": 1, "1x": 2, "class": 3, "valid": 4}
        ns = to_namespace(payload)

        self.assertEqual(getattr(ns, ""), 1)
        self.assertEqual(ns._, 1)  # pylint: disable=protected-access
        self.assertEqual(ns._1x, 2)  # pylint: disable=protected-access
        self.assertEqual(ns.class_, 3)  # pylint: disable=protected-access
        self.assertEqual(ns.valid, 4)
        self.assertEqual(ns._aliases["_"], "")  # pylint: disable=protected-access
        self.assertEqual(ns._aliases["_1x"], "1x")  # pylint: disable=protected-access
        self.assertEqual(ns._aliases["class_"], "class")  # pylint: disable=protected-access
        self.assertEqual(ns._raw["valid"], 4)  # pylint: disable=protected-access

    def test_to_namespace_collision_policies(self) -> None:
        payload = {"a-b": 1, "a_b": 2, "a_b__2": 3}

        suffix_ns = to_namespace(
            payload,
            NamespaceConfig(alias_collision_policy="suffix"),
        )
        self.assertEqual(suffix_ns.a_b, 2)
        self.assertEqual(getattr(suffix_ns, "a-b"), 1)
        self.assertEqual(suffix_ns.a_b__3, 1)  # pylint: disable=protected-access

        skip_ns = to_namespace(
            payload,
            NamespaceConfig(alias_collision_policy="skip"),
        )
        self.assertFalse(hasattr(skip_ns, "a_b__3"))
        self.assertFalse(hasattr(skip_ns, "_aliases"))

        with self.assertRaises(ValueError):
            to_namespace(payload, NamespaceConfig(alias_collision_policy="error"))

    def test_to_namespace_without_aliases_does_not_attach_alias_map(self) -> None:
        ns = to_namespace({"valid": 1}, NamespaceConfig(add_aliases=True))
        self.assertEqual(ns.valid, 1)
        self.assertFalse(hasattr(ns, "_aliases"))

    def test_to_namespace_can_disable_raw_and_alias_generation(self) -> None:
        ns = to_namespace(
            {"a-b": 1},
            NamespaceConfig(
                keep_raw=False,
                add_aliases=False,
            ),
        )
        self.assertEqual(getattr(ns, "a-b"), 1)
        self.assertFalse(hasattr(ns, "_raw"))
        self.assertFalse(hasattr(ns, "_aliases"))

    def test_nested_namespace_from_dict_noop_and_merge(self) -> None:
        ns = SimpleNamespace(existing=1)
        nested_namespace_from_dict(None, ns)
        self.assertEqual(ns.existing, 1)

        nested_namespace_from_dict({"child": {"name": "x"}}, ns)
        self.assertEqual(ns.child.name, "x")

        ns_non_namespace = SimpleNamespace()
        with patch(
            "mugen.core.utility.collection.namespace.to_namespace",
            return_value=[],
        ):
            nested_namespace_from_dict({"ignored": True}, ns_non_namespace)
        self.assertFalse(hasattr(ns_non_namespace, "ignored"))
