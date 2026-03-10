"""Tests for DI constructor kwarg compatibility filtering."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from mugen.core import di


class TestMugenDIConstructorKwargs(unittest.TestCase):
    """Covers constructor-kwarg filtering edge cases."""

    def test_signature_lookup_failure_returns_original_kwargs(self) -> None:
        provider_kwargs = {"config": object(), "logging_gateway": object()}

        with patch("mugen.core.di.inspect.signature", side_effect=TypeError("boom")):
            result = di._supported_constructor_kwargs(object, provider_kwargs)  # pylint: disable=protected-access

        self.assertEqual(result, provider_kwargs)


if __name__ == "__main__":
    unittest.main()
