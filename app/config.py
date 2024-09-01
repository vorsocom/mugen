"""Application configuration file."""

__all__ = ["AppConfig"]

import os

from quart import Quart


# pylint: disable=too-few-public-methods
class Config:
    """Base configuration class."""

    BASEDIR: str = os.path.abspath(os.path.dirname(__file__) + "/../")

    # Set log level.
    LOG_LEVEL: int = 10

    @staticmethod
    def init_app(app: Quart):
        """Configuration specific application initialisation."""
        app.logger.setLevel(app.config["LOG_LEVEL"])


class DevelopmentConfig(Config):
    """Development environment-specific configuration class"""

    # Set debug flag.
    DEBUG: bool = True


class TestingConfig(Config):
    """Testing environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL: int = 20

    # Set testing flag.
    TESTING: bool = True


class ProductionConfig(Config):
    """Production environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL: int = 30


AppConfig = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
