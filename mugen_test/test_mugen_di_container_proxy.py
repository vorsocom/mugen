"""Unit tests for lazy container lifecycle behavior in mugen.core.di."""

import unittest
import unittest.mock

from mugen.core import di


class TestDIContainerProxy(unittest.TestCase):
    """Unit tests for build_container/reset_container behavior."""

    def tearDown(self) -> None:
        di.reset_container()

    def test_build_container_caches_without_force(self):
        """build_container should cache and reuse injector when force is false."""
        first = object()
        second = object()

        di.reset_container()
        with unittest.mock.patch(
            "mugen.core.di._build_container",
            side_effect=[first, second],
        ) as build_mock:
            self.assertIs(di.build_container(), first)
            self.assertIs(di.build_container(), first)

        build_mock.assert_called_once()

    def test_build_container_force_rebuilds(self):
        """build_container(force=True) should rebuild and replace cached injector."""
        first = object()
        second = object()

        di.reset_container()
        with unittest.mock.patch(
            "mugen.core.di._build_container",
            side_effect=[first, second],
        ) as build_mock:
            self.assertIs(di.build_container(), first)
            self.assertIs(di.build_container(force=True), second)

        self.assertEqual(build_mock.call_count, 2)

    def test_reset_container_clears_cache(self):
        """reset_container should drop cached injector for the next build."""
        first = object()
        second = object()

        di.reset_container()
        with unittest.mock.patch(
            "mugen.core.di._build_container",
            side_effect=[first, second],
        ) as build_mock:
            self.assertIs(di.build_container(), first)
            di.reset_container()
            self.assertIs(di.build_container(), second)

        self.assertEqual(build_mock.call_count, 2)
