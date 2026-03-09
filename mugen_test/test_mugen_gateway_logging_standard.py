"""Unit tests for mugen.core.gateway.logging.standard.StandardLoggingGateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.gateway.logging.standard import StandardLoggingGateway


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            logger=SimpleNamespace(
                name="mugen.test.logger",
                level=10,
            )
        )
    )


class TestMugenGatewayLoggingStandard(unittest.TestCase):
    """Covers logger wiring and passthrough methods."""

    def test_init_and_passthrough_methods(self) -> None:
        logger = Mock()
        stream_handler = Mock()
        formatter = Mock()

        with (
            patch(
                "mugen.core.gateway.logging.standard.logging.getLogger",
                return_value=logger,
            ) as get_logger,
            patch(
                "mugen.core.gateway.logging.standard.logging.StreamHandler",
                return_value=stream_handler,
            ),
            patch(
                "mugen.core.gateway.logging.standard.logging.Formatter",
                return_value=formatter,
            ),
        ):
            gateway = StandardLoggingGateway(_config())

        get_logger.assert_called_once_with("mugen.test.logger")
        logger.setLevel.assert_called_once_with(10)
        stream_handler.setFormatter.assert_called_once_with(formatter)
        logger.addHandler.assert_called_once_with(stream_handler)

        gateway.critical("critical")
        gateway.debug("debug")
        gateway.error("error")
        gateway.info("info")
        gateway.warning("warning")

        logger.critical.assert_called_once_with("critical")
        logger.debug.assert_called_once_with("debug")
        logger.error.assert_called_once_with("error")
        logger.info.assert_called_once_with("info")
        logger.warning.assert_called_once_with("warning")

    def test_init_skips_new_handler_when_marked_console_handler_exists(self) -> None:
        existing_handler = Mock()
        setattr(
            existing_handler,
            StandardLoggingGateway._handler_marker,  # pylint: disable=protected-access
            True,
        )
        logger = Mock()
        logger.handlers = [existing_handler]

        with (
            patch(
                "mugen.core.gateway.logging.standard.logging.getLogger",
                return_value=logger,
            ) as get_logger,
            patch("mugen.core.gateway.logging.standard.logging.StreamHandler") as handler_cls,
        ):
            StandardLoggingGateway(_config())

        get_logger.assert_called_once_with("mugen.test.logger")
        logger.setLevel.assert_called_once_with(10)
        handler_cls.assert_not_called()
        logger.addHandler.assert_not_called()
