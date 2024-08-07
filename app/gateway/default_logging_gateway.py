"""Provides a logging gateway."""

__all__ = ["DefaultLoggingGateway"]

import logging

from app.contract.logging_gateway import ILoggingGateway


class DefaultLoggingGateway(ILoggingGateway):
    """A logging gateway based on the standard Python logging module."""

    def __init__(self, log_level: int) -> None:
        self._logger = logging.getLogger("COM.VORSOCOMPUTING.GLORIA")
        self._logger.setLevel(log_level)

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
