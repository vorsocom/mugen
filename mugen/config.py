"""Application configuration file."""

__all__ = ["AppConfig"]

import os

from quart import Quart


class Config:  # pylint: disable=too-few-public-methods
    """Base configuration class."""

    BASEDIR: str = os.path.abspath(os.path.dirname(__file__) + "/../")

    # Set log level.
    LOG_LEVEL: int = 10

    @staticmethod
    def init_app(mugen: Quart):
        """Configuration specific application initialisation."""
        mugen.logger.setLevel(mugen.config["LOG_LEVEL"])


class DevelopmentConfig(Config):  # pylint: disable=too-few-public-methods
    """Development environment-specific configuration class"""

    # Set debug flag.
    DEBUG: bool = True


class TestingConfig(Config):  # pylint: disable=too-few-public-methods
    """Testing environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL: int = 20

    # Set testing flag.
    TESTING: bool = True


class ProductionConfig(Config):  # pylint: disable=too-few-public-methods
    """Production environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL: int = 30


AppConfig = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
