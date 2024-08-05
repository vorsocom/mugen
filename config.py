"""Application configuration file."""

import os

__all__ = ["AppConfig"]

APP_PREFIX = "BLOGGINS"
BASEDIR = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    """Base configuration class."""

    # Maintain reference to the base directory of the code base to be used application
    # wide.
    BASEDIR = BASEDIR

    @staticmethod
    def init_app(app):
        """Perform configuration specific initialization."""


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
