"""Application configuration file."""

__all__ = ["AppConfig"]

import os

from quart import Quart

APP_PREFIX = "GLORIA"
BASEDIR = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    """Base configuration class."""

    # Maintain reference to the base directory of the code base to be used application
    # wide.
    BASEDIR = BASEDIR

    @staticmethod
    def init_app(app: Quart):
        """Configuration specific application initialisation."""
        app.logger.setLevel(app.config["LOG_LEVEL"])


class DevelopmentConfig(Config):
    """Development environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL = 10

    # Set debug flag.
    DEBUG = True


class TestingConfig(Config):
    """Testing environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL = 20

    # Set testing flag.
    TESTING = True


class ProductionConfig(Config):
    """Production environment-specific configuration class"""

    # Set log level.
    LOG_LEVEL = 30


AppConfig = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
