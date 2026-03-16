"""Application configuration file."""

__all__ = ["AppConfig"]

import os
from types import SimpleNamespace

from quart import Quart

from mugen.core.utility.security import validate_quart_secret_key


class Config:  # pylint: disable=too-few-public-methods
    """Base configuration class."""

    BASEDIR: str = os.path.abspath(os.path.dirname(__file__) + "/../")

    # Clear debug flag.
    DEBUG: bool = False

    # Set log level.
    LOG_LEVEL: int = 10

    @staticmethod
    def init_app(app: Quart, config: SimpleNamespace):
        """Configuration specific application initialisation."""
        try:
            app.logger.setLevel(app.config["LOG_LEVEL"])
        except KeyError:
            app.logger.error("LOG_LEVEL not configured.")

        quart_config = getattr(config, "quart", None)
        if quart_config is None:
            raise RuntimeError("Invalid configuration: [quart] section is required.")
        app.config["SECRET_KEY"] = validate_quart_secret_key(
            getattr(quart_config, "secret_key", None)
        )


class DevelopmentConfig(Config):  # pylint: disable=too-few-public-methods
    """Development environment-specific configuration class"""

    # Set debug flag.
    DEBUG: bool = True


class TestingConfig(Config):  # pylint: disable=too-few-public-methods
    """Testing environment-specific configuration class"""

    # Set debug flag.
    DEBUG: bool = True

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
