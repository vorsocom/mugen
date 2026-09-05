"""Tests shared knowledge gateway configuration helpers."""

import unittest
from types import SimpleNamespace

from mugen.core.gateway.knowledge.common import resolve_hugging_face_token


class TestMugenGatewayKnowledgeCommon(unittest.TestCase):
    """Coverage for provider-neutral knowledge gateway helpers."""

    def test_resolve_hugging_face_token_normalizes_configured_value(self) -> None:
        """Configured token text is trimmed before use."""
        self.assertEqual(
            resolve_hugging_face_token(SimpleNamespace(token=" test-hf-token ")),
            "test-hf-token",
        )

    def test_resolve_hugging_face_token_treats_omitted_and_blank_as_absent(
        self,
    ) -> None:
        """Missing and blank token values keep authentication disabled."""
        self.assertIsNone(resolve_hugging_face_token(None))
        self.assertIsNone(resolve_hugging_face_token(SimpleNamespace()))
        self.assertIsNone(resolve_hugging_face_token(SimpleNamespace(token="")))
        self.assertIsNone(resolve_hugging_face_token(SimpleNamespace(token=" \t ")))

    def test_resolve_hugging_face_token_rejects_non_string_without_value(self) -> None:
        """Invalid token types fail without rendering their contents."""
        secret_marker = "sensitive-value-marker"
        with self.assertRaises(RuntimeError) as raised:
            resolve_hugging_face_token(SimpleNamespace(token={secret_marker: True}))

        message = str(raised.exception)
        self.assertEqual(
            message,
            "Invalid configuration: transformers.hf.token must be a string.",
        )
        self.assertNotIn(secret_marker, message)
