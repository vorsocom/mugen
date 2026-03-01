"""Unit tests for config-driven media gateway provider helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest

from mugen.core.gateway.storage.media.provider import DefaultMediaStorageGateway


class TestMediaProviderHelpers(unittest.TestCase):
    """Cover path resolution branches in media gateway provider."""

    def test_resolve_storage_path_preserves_absolute_path(self) -> None:
        gateway = DefaultMediaStorageGateway.__new__(DefaultMediaStorageGateway)
        gateway._config = SimpleNamespace(basedir="/tmp/base")  # pylint: disable=protected-access
        absolute_path = os.path.abspath("/tmp/media-path")

        resolved = gateway._resolve_storage_path(absolute_path)  # pylint: disable=protected-access

        self.assertEqual(resolved, absolute_path)
