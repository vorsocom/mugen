"""Tests shared knowledge gateway configuration helpers."""

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from mugen.core.gateway.knowledge.common import (
    DEFAULT_ENCODER_REVISION,
    resolve_encoder_revision,
    resolve_hugging_face_token,
)


class TestMugenGatewayKnowledgeCommon(unittest.TestCase):
    """Coverage for provider-neutral knowledge gateway helpers."""

    def test_default_model_uses_reviewed_immutable_revision(self) -> None:
        for model in (
            "all-mpnet-base-v2",
            "sentence-transformers/all-mpnet-base-v2",
        ):
            self.assertEqual(
                resolve_encoder_revision(model, None), DEFAULT_ENCODER_REVISION
            )

    def test_custom_model_requires_operator_reviewed_commit(self) -> None:
        revision = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(
            resolve_encoder_revision(
                "trusted/model", SimpleNamespace(revision=revision)
            ),
            revision,
        )
        for revision in (None, "", "main", "v1", "a" * 39, "g" * 40, 123):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(RuntimeError, "full, reviewed"):
                    resolve_encoder_revision(
                        "trusted/model", SimpleNamespace(revision=revision)
                    )

    def test_local_paths_and_shadowed_repository_names_cannot_bypass_pin(self) -> None:
        with TemporaryDirectory() as folder, chdir(folder):
            Path("all-mpnet-base-v2").mkdir()
            Path("relative-model").mkdir()
            Path("sentence-transformers/all-mpnet-base-v2").mkdir(parents=True)
            for model in (
                folder,
                "../relative-model",
                "relative-model",
                "all-mpnet-base-v2",
                "sentence-transformers/all-mpnet-base-v2",
                "C:\\models\\encoder",
            ):
                with self.subTest(model=model):
                    with self.assertRaisesRegex(RuntimeError, "local path"):
                        resolve_encoder_revision(
                            model, SimpleNamespace(revision="a" * 40)
                        )
            with self.assertRaisesRegex(RuntimeError, "local path"):
                resolve_encoder_revision("all-mpnet-base-v2", None)

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
