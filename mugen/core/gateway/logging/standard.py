"""Provides a logging gateway."""

__all__ = ["StandardLoggingGateway"]

import logging

from mugen.core.contract.gateway.logging import ILoggingGateway


class StandardLoggingGateway(ILoggingGateway):
    """A logging gateway based on the standard Python logging module."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._logger = logging.getLogger(self._config.mugen.logger.name)
        self._logger.setLevel(self._config.mugen.logger.level)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(
                "[{asctime}] {name} {levelname}: {message}",
                style="{",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self._logger.addHandler(console_handler)

    def critical(self, message: str):
        self._logger.critical(message)

    def debug(self, message: str):
        self._logger.debug(message)

    def error(self, message: str):
        self._logger.error(message)

    def info(self, message: str):
        self._logger.info(message)

    def warning(self, message: str):
        self._logger.warning(message)
