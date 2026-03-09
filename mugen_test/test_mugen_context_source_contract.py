"""Unit tests for context source identity and policy contracts."""

from __future__ import annotations

import unittest

from mugen.core.contract.context import (
    ContextSourcePolicyEffect,
    ContextSourceRef,
    ContextSourceRule,
)


class TestContextSourceContracts(unittest.TestCase):
    """Covers validation and match semantics for source contract types."""

    def test_context_source_ref_normalizes_and_validates_fields(self) -> None:
        source_ref = ContextSourceRef(
            kind=" knowledge ",
            source_key=" kb-main ",
            source_id=" doc-1 ",
            canonical_locator=" https://example.invalid/doc-1 ",
            segment_id=" seg-1 ",
            locale=" en ",
            category=" faq ",
            metadata={"rank": 1},
        )

        self.assertEqual(source_ref.kind, "knowledge")
        self.assertEqual(source_ref.source_key, "kb-main")
        self.assertEqual(source_ref.source_id, "doc-1")
        self.assertEqual(
            source_ref.canonical_locator,
            "https://example.invalid/doc-1",
        )
        self.assertEqual(source_ref.segment_id, "seg-1")
        self.assertEqual(source_ref.locale, "en")
        self.assertEqual(source_ref.category, "faq")
        self.assertEqual(source_ref.metadata, {"rank": 1})

        empty_source_ref = ContextSourceRef(
            kind="knowledge",
            source_key=" ",
            metadata=None,
        )
        self.assertIsNone(empty_source_ref.source_key)
        self.assertEqual(empty_source_ref.metadata, {})

        with self.assertRaisesRegex(TypeError, "must be strings or None"):
            ContextSourceRef(kind=123)
        with self.assertRaisesRegex(ValueError, "ContextSourceRef.kind is required"):
            ContextSourceRef(kind=" ")
        with self.assertRaisesRegex(
            TypeError,
            "ContextSourceRef.metadata must be a dict",
        ):
            ContextSourceRef(kind="knowledge", metadata=["bad"])

    def test_context_source_rule_requires_source_ref_and_matches(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "ContextSourceRule.effect must be ContextSourcePolicyEffect",
        ):
            ContextSourceRule(effect="allow")

        rule = ContextSourceRule(
            effect=ContextSourcePolicyEffect.ALLOW,
            kind=" knowledge ",
            source_key=" kb-main ",
            locale=" en ",
            category=" faq ",
            metadata=None,
        )
        self.assertTrue(rule.requires_source_ref())
        self.assertEqual(rule.metadata, {})
        self.assertEqual(
            rule.descriptor(),
            {
                "effect": "allow",
                "kind": "knowledge",
                "source_key": "kb-main",
                "locale": "en",
                "category": "faq",
            },
        )

        matching_source = ContextSourceRef(
            kind="knowledge",
            source_key="kb-main",
            locale="en",
            category="faq",
        )
        self.assertTrue(rule.matches(matching_source))
        self.assertFalse(rule.matches(None, source_kind="knowledge"))
        self.assertFalse(
            rule.matches(
                ContextSourceRef(
                    kind="knowledge",
                    source_key="other",
                    locale="en",
                    category="faq",
                )
            )
        )
        self.assertFalse(
            rule.matches(
                ContextSourceRef(
                    kind="knowledge",
                    source_key="kb-main",
                    locale="fr",
                    category="faq",
                )
            )
        )
        self.assertFalse(
            rule.matches(
                ContextSourceRef(
                    kind="knowledge",
                    source_key="kb-main",
                    locale="en",
                    category="guide",
                )
            )
        )

        kind_only_rule = ContextSourceRule(
            effect=ContextSourcePolicyEffect.DENY,
            kind="knowledge",
        )
        self.assertFalse(kind_only_rule.requires_source_ref())
        self.assertTrue(kind_only_rule.matches(None, source_kind=" knowledge "))
