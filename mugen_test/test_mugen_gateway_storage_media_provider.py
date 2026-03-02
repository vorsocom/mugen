"""Unit tests for config-driven media gateway provider helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mugen.core.gateway.storage.media.provider import DefaultMediaStorageGateway
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway


class TestMediaProviderHelpers(unittest.TestCase):
    """Cover path resolution branches in media gateway provider."""

    def test_default_backend_is_object_storage(self) -> None:
        gateway = DefaultMediaStorageGateway(
            config=SimpleNamespace(
                basedir="/tmp/base",
                mugen=SimpleNamespace(environment="development"),
                web=SimpleNamespace(
                    media=SimpleNamespace(
                        storage=SimpleNamespace(path="web_media"),
                        object=SimpleNamespace(
                            cache_path="web_media_object_cache",
                            key_prefix="web:media:object",
                        ),
                    )
                ),
            ),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
        )

        self.assertIsInstance(gateway._backend, ObjectMediaStorageGateway)  # pylint: disable=protected-access

    def test_rejects_non_object_backend(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "web.media.backend must be 'object'",
        ):
            DefaultMediaStorageGateway(
                config=SimpleNamespace(
                    basedir="/tmp/base",
                    mugen=SimpleNamespace(environment="development"),
                    web=SimpleNamespace(
                        media=SimpleNamespace(
                            backend="filesystem",
                            storage=SimpleNamespace(path="web_media"),
                        )
                    ),
                ),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
            )

    def test_resolve_storage_path_preserves_absolute_path(self) -> None:
        gateway = DefaultMediaStorageGateway.__new__(DefaultMediaStorageGateway)
        gateway._config = SimpleNamespace(basedir="/tmp/base")  # pylint: disable=protected-access
        absolute_path = os.path.abspath("/tmp/media-path")

        resolved = gateway._resolve_storage_path(absolute_path)  # pylint: disable=protected-access

        self.assertEqual(resolved, absolute_path)
