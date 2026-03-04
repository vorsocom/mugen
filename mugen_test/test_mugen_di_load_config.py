"""Provides unit tests for mugen.core.di"""

from textwrap import dedent
import unittest
import unittest.mock

from mugen.core import di


def _minimal_core_config() -> dict:
    return {
        "rdbms": {
            "migration_tracks": {
                "core": {
                    "schema": "mugen",
                }
            }
        },
        "mugen": {
            "runtime": {
                "profile": "platform_full",
                "provider_readiness_timeout_seconds": 15.0,
                "provider_shutdown_timeout_seconds": 10.0,
                "shutdown_timeout_seconds": 60.0,
                "phase_b": {
                    "startup_timeout_seconds": 30.0,
                    "readiness_grace_seconds": 0.0,
                    "critical_platforms": [],
                    "degrade_on_critical_exit": True,
                },
            },
            "messaging": {
                "mh_mode": "optional",
            },
            "modules": {
                "core": {
                    "client": {
                        "matrix": "default",
                        "whatsapp": "default",
                        "web": "default",
                    },
                    "gateway": {
                        "completion": "deterministic",
                        "logging": "standard",
                        "storage": {
                            "keyval": "relational",
                            "media": "default",
                            "relational": "sqlalchemy",
                            "web_runtime": "relational",
                        },
                    },
                    "service": {
                        "ipc": "default",
                        "messaging": "default",
                        "nlp": "default",
                        "platform": "default",
                        "user": "default",
                    },
                    "extensions": [],
                },
                "extensions": [],
            },
            "platforms": [],
        },
    }


# pylint: disable=protected-access
class TestDILoadConfig(unittest.TestCase):
    """Unit tests for mugen.core.di"""

    def test_config_file_not_found(self) -> None:
        """Test effects of unavailable config file."""

        with self.assertRaises(di.ContainerBootstrapError):
            di._load_config("unavailable_file.toml")

    def test_config_file_is_available(self) -> None:
        """Test effects of available config file."""

        # Create dummy toml content.
        env = "testing"
        toml_content = f"""\
        [mugen]
        environment = "{env}"
        """

        # Create dummy file to patch builtins.open.
        toml_file = unittest.mock.mock_open(read_data=dedent(toml_content))

        # Patch builtins.open in this context.
        with unittest.mock.patch(target="builtins.open", new=toml_file):
            try:
                config = di._load_config("")
                self.assertIsInstance(config, dict)
                self.assertEqual(config["mugen"]["environment"], env)
            except:  # pylint: disable=bare-except
                # If we get here the test has failed since
                # the configuration should've been loaded
                # successfully and no exceptions should've
                # been raised.
                self.fail("Exception raised unexpectedly.")

    def test_build_container_uses_default_config_file_when_env_unset(self) -> None:
        """Build container should default to mugen.toml."""

        load_config = unittest.mock.Mock(return_value=_minimal_core_config())
        injector = unittest.mock.Mock()

        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            with unittest.mock.patch(
                target="mugen.core.di._load_config",
                new=load_config,
            ):
                with unittest.mock.patch(
                    target="mugen.core.di.DependencyInjector",
                    return_value=injector,
                ):
                    with unittest.mock.patch(
                        target="mugen.core.di._build_config_provider",
                    ):
                        with unittest.mock.patch(
                            target="mugen.core.di._build_provider",
                        ):
                            with unittest.mock.patch(
                                target="mugen.core.di._build_shared_relational_runtime",
                            ):
                                with unittest.mock.patch(
                                    target="mugen.core.di._validate_container",
                                ):
                                    di._build_container()

        load_config.assert_called_once_with("mugen.toml")

    def test_build_container_uses_env_config_file_override(self) -> None:
        """Build container should honor MUGEN_CONFIG_FILE override."""

        load_config = unittest.mock.Mock(return_value=_minimal_core_config())
        injector = unittest.mock.Mock()
        override = "mugen.override.toml"

        with unittest.mock.patch.dict(
            "os.environ",
            {"MUGEN_CONFIG_FILE": override},
            clear=True,
        ):
            with unittest.mock.patch(
                target="mugen.core.di._load_config",
                new=load_config,
            ):
                with unittest.mock.patch(
                    target="mugen.core.di.DependencyInjector",
                    return_value=injector,
                ):
                    with unittest.mock.patch(
                        target="mugen.core.di._build_config_provider",
                    ):
                        with unittest.mock.patch(
                            target="mugen.core.di._build_provider",
                        ):
                            with unittest.mock.patch(
                                target="mugen.core.di._build_shared_relational_runtime",
                            ):
                                with unittest.mock.patch(
                                    target="mugen.core.di._validate_container",
                                ):
                                    di._build_container()

        load_config.assert_called_once_with(override)

    def test_resolve_config_file_falls_back_for_non_string(self) -> None:
        """Non-string getenv responses should fall back to mugen.toml."""

        with unittest.mock.patch(
            target="mugen.core.di.os.getenv",
            return_value=123,
        ):
            self.assertEqual(di._resolve_config_file(), "mugen.toml")

    def test_resolve_config_file_falls_back_for_empty_string(self) -> None:
        """Empty override should fall back to mugen.toml."""

        with unittest.mock.patch(
            target="mugen.core.di.os.getenv",
            return_value="   ",
        ):
            self.assertEqual(di._resolve_config_file(), "mugen.toml")
