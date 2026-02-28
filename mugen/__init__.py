"""Quart application package."""

__all__ = [
    "BOOTSTRAP_STATE_KEY",
    "BootstrapConfigError",
    "BootstrapError",
    "ExtensionLoadError",
    "MUGEN_EXTENSION_KEY",
    "PHASE_A_STATUS_KEY",
    "PHASE_B_ERROR_KEY",
    "PHASE_B_PLATFORM_ERRORS_KEY",
    "PHASE_B_PLATFORM_STATUSES_KEY",
    "PHASE_B_STARTED_AT_KEY",
    "PHASE_B_STATUS_KEY",
    "PHASE_STATUS_DEGRADED",
    "PHASE_STATUS_HEALTHY",
    "PHASE_STATUS_STARTING",
    "PHASE_STATUS_STOPPED",
    "SHUTDOWN_REQUESTED_KEY",
    "bootstrap_app",
    "create_quart_app",
    "get_bootstrap_state",
    "run_clients",
    "run_platform_clients",
    "run_web_client",
    "validate_web_relational_runtime_config",
    "validate_phase_b_runtime_config",
]

import asyncio
from importlib import import_module
import random
import re
from time import perf_counter
from types import SimpleNamespace

from quart import Quart

from mugen.bootstrap_state import (
    BOOTSTRAP_STATE_KEY,
    MUGEN_EXTENSION_KEY,
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
    get_bootstrap_state,
)
from mugen.config import AppConfig
from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.utility.platforms import (
    SUPPORTED_CORE_PLATFORMS,
    normalize_platforms,
    unknown_platforms,
)

_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"


class BootstrapError(RuntimeError):
    """Base error type for application bootstrap failures."""


class BootstrapConfigError(BootstrapError):
    """Raised when bootstrap configuration is invalid."""


class ExtensionLoadError(BootstrapError):
    """Raised when an extension cannot be loaded or initialized."""


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _whatsapp_provider():
    return di.container.whatsapp_client


def _ipc_provider():
    return di.container.ipc_service


def _messaging_provider():
    return di.container.messaging_service


def _platform_provider():
    return di.container.platform_service


def _telnet_provider():
    return di.container.telnet_client


def _matrix_provider():
    return di.container.matrix_client


def _web_provider():
    return di.container.web_client


def _relational_storage_gateway_provider():
    return di.container.relational_storage_gateway


def _extension_enabled(ext: SimpleNamespace) -> bool:
    """Resolve whether an extension is enabled by configuration."""
    raw_enabled = getattr(ext, "enabled", True)
    if isinstance(raw_enabled, str):
        normalized = raw_enabled.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(raw_enabled)


def _telnet_allowed_in_production(config: SimpleNamespace) -> bool:
    raw_value = getattr(
        getattr(config, "telnet", SimpleNamespace()),
        "allow_in_production",
        False,
    )
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return False


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_platform_list(values: object) -> list[str]:
    return normalize_platforms(values)


def _config_path_exists(config: object, *path: str) -> bool:
    current = config
    for key in path:
        if current is None:
            return False
        if isinstance(current, dict):
            if key not in current:
                return False
            current = current[key]
            continue
        current_dict = getattr(current, "__dict__", None)
        if isinstance(current_dict, dict):
            if key not in current_dict:
                return False
            current = current_dict[key]
            continue
        try:
            current = getattr(current, key)
        except AttributeError:
            return False
    return True


def validate_web_relational_runtime_config(
    *,
    config: SimpleNamespace,
    active_platforms: list[str],
    relational_storage_gateway_provider=_relational_storage_gateway_provider,
) -> None:
    """Validate relational web runtime dependencies before task scheduling."""
    if "web" not in active_platforms:
        return

    relational_configured = _config_path_exists(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "storage",
        "relational",
    )
    if relational_configured is not True:
        return

    relational_storage_gateway = relational_storage_gateway_provider()
    if relational_storage_gateway is None:
        raise BootstrapConfigError(
            "Relational web storage is configured but "
            "relational_storage_gateway provider is unavailable."
        )

    raw_session = getattr(relational_storage_gateway, "raw_session", None)
    if callable(raw_session):
        return

    raise BootstrapConfigError(
        "Relational web storage is configured but "
        "relational_storage_gateway.raw_session is unavailable."
    )


def _resolve_phase_b_critical_platforms(
    config: SimpleNamespace,
    bootstrap_state: dict,
    active_platforms: list[str],
) -> list[str]:
    configured = bootstrap_state.get(_PHASE_B_CRITICAL_PLATFORMS_KEY)
    resolved = _normalize_platform_list(configured)
    if resolved:
        return resolved

    runtime_cfg = getattr(getattr(config, "mugen", SimpleNamespace()), "runtime", None)
    phase_b_cfg = getattr(runtime_cfg, "phase_b", None)
    resolved = _normalize_platform_list(getattr(phase_b_cfg, "critical_platforms", None))
    if resolved:
        return resolved

    return list(active_platforms)


def validate_phase_b_runtime_config(
    *,
    config: SimpleNamespace,
    bootstrap_state: dict,
    logger: ILoggingGateway | None = None,
) -> tuple[list[str], list[str], bool]:
    """Resolve and validate runtime platform configuration for phase B."""
    raw_platforms = getattr(getattr(config, "mugen", SimpleNamespace()), "platforms", None)
    if not isinstance(raw_platforms, list):
        if logger is not None:
            logger.error("Invalid platform configuration.")
        raise BootstrapConfigError("Invalid platform configuration.")

    active_platforms = _normalize_platform_list(raw_platforms)
    unsupported_platforms = unknown_platforms(active_platforms)
    if unsupported_platforms:
        supported_platforms_text = ", ".join(sorted(SUPPORTED_CORE_PLATFORMS))
        unsupported_platforms_text = ", ".join(unsupported_platforms)
        raise BootstrapConfigError(
            "Invalid platform configuration. "
            "mugen.platforms includes unsupported platform(s): "
            f"{unsupported_platforms_text}. "
            f"Supported platforms: {supported_platforms_text}."
        )

    environment = str(
        getattr(getattr(config, "mugen", SimpleNamespace()), "environment", "")
    ).strip().lower()
    if "telnet" in active_platforms and environment == "production":
        if _telnet_allowed_in_production(config) is not True:
            raise BootstrapConfigError(
                "Telnet platform is disabled in production. Set "
                "telnet.allow_in_production=true to override."
            )

    critical_platforms = _resolve_phase_b_critical_platforms(
        config,
        bootstrap_state,
        active_platforms,
    )
    unsupported_critical_platforms = unknown_platforms(critical_platforms)
    if unsupported_critical_platforms:
        supported_platforms_text = ", ".join(sorted(SUPPORTED_CORE_PLATFORMS))
        unsupported_platforms_text = ", ".join(unsupported_critical_platforms)
        raise BootstrapConfigError(
            "Invalid runtime critical platform configuration. "
            "mugen.runtime.phase_b.critical_platforms includes unsupported platform(s): "
            f"{unsupported_platforms_text}. "
            f"Supported platforms: {supported_platforms_text}."
        )

    invalid_critical_platforms = [
        platform
        for platform in critical_platforms
        if platform not in active_platforms
    ]
    if invalid_critical_platforms:
        active_platforms_text = ", ".join(active_platforms) if active_platforms else "<none>"
        invalid_platforms_text = ", ".join(invalid_critical_platforms)
        raise BootstrapConfigError(
            "Invalid runtime critical platform configuration. "
            "mugen.runtime.phase_b.critical_platforms includes unsupported platform(s): "
            f"{invalid_platforms_text}. Enabled platforms: {active_platforms_text}."
        )

    degrade_on_critical_exit = _resolve_degrade_on_critical_exit(config, bootstrap_state)
    return active_platforms, critical_platforms, degrade_on_critical_exit


def _resolve_degrade_on_critical_exit(config: SimpleNamespace, bootstrap_state: dict) -> bool:
    state_value = bootstrap_state.get(_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY)
    if state_value is not None:
        return _parse_bool(state_value, default=True)

    runtime_cfg = getattr(getattr(config, "mugen", SimpleNamespace()), "runtime", None)
    phase_b_cfg = getattr(runtime_cfg, "phase_b", None)
    raw_value = getattr(phase_b_cfg, "degrade_on_critical_exit", True)
    return _parse_bool(raw_value, default=True)


def _ensure_platform_state(
    bootstrap_state: dict,
    *,
    active_platforms: list[str],
) -> tuple[dict[str, str], dict[str, str | None]]:
    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY)
    if not isinstance(statuses, dict):
        statuses = {}

    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY)
    if not isinstance(errors, dict):
        errors = {}

    for platform in active_platforms:
        statuses.setdefault(platform, PHASE_STATUS_STARTING)
        errors.setdefault(platform, None)

    bootstrap_state[PHASE_B_PLATFORM_STATUSES_KEY] = statuses
    bootstrap_state[PHASE_B_PLATFORM_ERRORS_KEY] = errors
    return statuses, errors


def _set_platform_status(
    bootstrap_state: dict,
    *,
    platform: str,
    status: str,
    error: str | None,
) -> None:
    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY)
    if not isinstance(statuses, dict):
        statuses = {}
    statuses[platform] = status
    bootstrap_state[PHASE_B_PLATFORM_STATUSES_KEY] = statuses

    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY)
    if not isinstance(errors, dict):
        errors = {}
    errors[platform] = error
    bootstrap_state[PHASE_B_PLATFORM_ERRORS_KEY] = errors


def _refresh_phase_b_status(
    bootstrap_state: dict,
    *,
    critical_platforms: list[str],
    degrade_on_critical_exit: bool = True,
) -> None:
    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY)
    if not isinstance(statuses, dict):
        statuses = {}
    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY)
    if not isinstance(errors, dict):
        errors = {}

    shutdown_requested = _parse_bool(
        bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
        default=False,
    )
    if shutdown_requested:
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
        bootstrap_state[PHASE_B_ERROR_KEY] = None
        return

    if not critical_platforms:
        critical_platforms = list(statuses.keys())

    degraded: list[str] = []
    starting: list[str] = []
    unexpected: list[str] = []
    for platform in critical_platforms:
        platform_status = str(statuses.get(platform, PHASE_STATUS_STARTING) or "")
        if platform_status == PHASE_STATUS_DEGRADED:
            degraded.append(platform)
            continue
        if platform_status == PHASE_STATUS_STARTING:
            starting.append(platform)
            continue
        if (
            platform_status == PHASE_STATUS_STOPPED
            and degrade_on_critical_exit is not True
        ):
            continue
        if platform_status not in {PHASE_STATUS_HEALTHY}:
            unexpected.append(platform)

    if degraded:
        first_platform = degraded[0]
        details = errors.get(first_platform)
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        bootstrap_state[PHASE_B_ERROR_KEY] = (
            f"{first_platform}: {details}" if details else f"{first_platform}: degraded"
        )
        return

    if unexpected:
        first_platform = unexpected[0]
        details = errors.get(first_platform)
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        bootstrap_state[PHASE_B_ERROR_KEY] = (
            f"{first_platform}: {details}"
            if details
            else f"{first_platform}: stopped unexpectedly"
        )
        return

    if starting:
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        bootstrap_state[PHASE_B_ERROR_KEY] = None
        return

    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
    bootstrap_state[PHASE_B_ERROR_KEY] = None


def _split_extension_path(path: str) -> tuple[str, str | None]:
    """Split extension path into module and optional class target."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Extension path must be a non-empty string.")

    normalized = path.strip()
    if ":" not in normalized:
        return normalized, None

    module_name, class_name = normalized.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("Extension path must use module:ClassName.")

    return module_name, class_name


def _resolve_extension_class(
    *,
    interface: type,
    module_name: str,
    class_name: str | None,
    ext_path: str,
) -> type:
    """Resolve extension class deterministically for the configured path."""
    if class_name is not None:
        module = import_module(name=module_name)
        ext_class = getattr(module, class_name, None)
        if not isinstance(ext_class, type):
            raise ExtensionLoadError(f"Extension class not found: {ext_path}.")
        if not issubclass(ext_class, interface):
            raise ExtensionLoadError(
                f"Extension class is not a valid {interface.__name__}: {ext_path}."
            )
        return ext_class

    module_matches = [x for x in interface.__subclasses__() if x.__module__ == module_name]
    if not module_matches:
        raise ExtensionLoadError(
            f"Extension is not a subclass of its intended type: {ext_path}."
        )

    if len(module_matches) > 1:
        candidates = ", ".join(
            sorted(x.__qualname__ for x in module_matches)
        )
        raise ExtensionLoadError(
            "Multiple extension classes found. "
            f"Use module:ClassName for deterministic resolution ({ext_path}). "
            f"Candidates: {candidates}."
        )

    return module_matches[0]


def create_quart_app(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
) -> Quart:
    """Application factory."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()

    # Create new Quart application.
    app = Quart(__name__)

    # Check for valid configuration name.
    try:
        environment = config.mugen.environment
    except AttributeError as exc:
        logger.error("Configuration unavailable.")
        raise BootstrapConfigError("Configuration unavailable.") from exc

    logger.debug(f"Configured environment: {environment}.")
    if environment not in (
        "default",
        "development",
        "testing",
        "production",
    ):
        logger.error("Invalid environment name.")
        raise BootstrapConfigError("Invalid environment name.")

    # Create application configuration object.
    app.config.from_object(AppConfig[environment])

    # Initialize application.
    AppConfig[environment].init_app(app, config)

    # Return the built application object.
    return app


# pylint: disable=too-many-branches
# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
# pylint: disable=too-many-statements
async def run_clients(
    app: Quart,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
    web_provider=_web_provider,
) -> None:
    """Entrypoint for assistants."""
    await bootstrap_app(app, config_provider=config_provider)
    await run_platform_clients(
        app,
        config_provider=config_provider,
        logger_provider=logger_provider,
        whatsapp_provider=whatsapp_provider,
        web_provider=web_provider,
    )


async def bootstrap_app(
    app: Quart,
    config_provider=_config_provider,
) -> None:
    """Phase A bootstrap for app extensions and API registration."""
    # Discover and register core plugins and
    # third-party extensions.
    await register_extensions(app, config_provider=config_provider)

    # Register blueprints after extensions have been loaded.
    # This allows extensions to hack the api.
    app.register_blueprint(api, url_prefix="/api")


async def run_platform_clients(
    app: Quart,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
    web_provider=_web_provider,
    relational_storage_gateway_provider=_relational_storage_gateway_provider,
) -> None:
    """Phase B bootstrap for long-running platform clients."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    bootstrap_state = get_bootstrap_state(app)
    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
    bootstrap_state[PHASE_B_ERROR_KEY] = None
    bootstrap_state[SHUTDOWN_REQUESTED_KEY] = False

    active_platforms, critical_platforms, degrade_on_critical_exit = (
        validate_phase_b_runtime_config(
            config=config,
            bootstrap_state=bootstrap_state,
            logger=logger,
        )
    )
    validate_web_relational_runtime_config(
        config=config,
        active_platforms=active_platforms,
        relational_storage_gateway_provider=relational_storage_gateway_provider,
    )
    bootstrap_state[_PHASE_B_CRITICAL_PLATFORMS_KEY] = critical_platforms
    bootstrap_state[_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = degrade_on_critical_exit
    _ensure_platform_state(
        bootstrap_state,
        active_platforms=active_platforms,
    )

    tasks: dict[str, asyncio.Task] = {}

    def _on_platform_started(platform_name: str) -> None:
        shutdown_requested = _parse_bool(
            bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
            default=False,
        )
        if shutdown_requested:
            return
        _set_platform_status(
            bootstrap_state,
            platform=platform_name,
            status=PHASE_STATUS_HEALTHY,
            error=None,
        )
        _refresh_phase_b_status(
            bootstrap_state,
            critical_platforms=critical_platforms,
            degrade_on_critical_exit=degrade_on_critical_exit,
        )

    def _invoke_platform_runner(platform_name: str, runner) -> object:
        started_signalled = False

        def _started_callback() -> None:
            nonlocal started_signalled
            if started_signalled:
                return
            started_signalled = True
            _on_platform_started(platform_name)

        try:
            return runner(started_callback=_started_callback)
        except TypeError as exc:
            if "started_callback" not in str(exc):
                raise

        async def _legacy_runner() -> None:
            _started_callback()
            await runner()

        return _legacy_runner()

    def _on_platform_task_done(platform_name: str, task: asyncio.Task) -> None:
        shutdown_requested = _parse_bool(
            bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
            default=False,
        )
        try:
            error = task.exception()
        except asyncio.CancelledError:
            if shutdown_requested:
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_STOPPED,
                    error=None,
                )
                logger.debug(f"{platform_name} client cancelled during shutdown.")
            else:
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_DEGRADED,
                    error="cancelled unexpectedly",
                )
                logger.error(f"{platform_name} client cancelled unexpectedly.")
            _refresh_phase_b_status(
                bootstrap_state,
                critical_platforms=critical_platforms,
                degrade_on_critical_exit=degrade_on_critical_exit,
            )
            return

        if error is None:
            if shutdown_requested:
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_STOPPED,
                    error=None,
                )
                logger.debug(f"{platform_name} client stopped during shutdown.")
            elif (
                platform_name in critical_platforms
                and degrade_on_critical_exit is True
            ):
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_DEGRADED,
                    error="critical platform exited unexpectedly",
                )
                logger.error(
                    f"{platform_name} client exited unexpectedly without exception."
                )
            else:
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_STOPPED,
                    error=None,
                )
                logger.warning(f"{platform_name} client stopped.")
            _refresh_phase_b_status(
                bootstrap_state,
                critical_platforms=critical_platforms,
                degrade_on_critical_exit=degrade_on_critical_exit,
            )
            return

        error_message = f"{type(error).__name__}: {error}"
        _set_platform_status(
            bootstrap_state,
            platform=platform_name,
            status=PHASE_STATUS_DEGRADED,
            error=error_message,
        )
        _refresh_phase_b_status(
            bootstrap_state,
            critical_platforms=critical_platforms,
            degrade_on_critical_exit=degrade_on_critical_exit,
        )
        logger.error(
            f"{platform_name} client failed ({error_message})."
        )

    try:
        if "matrix" in active_platforms:
            logger.debug("Running matrix client.")
            task = asyncio.create_task(
                _invoke_platform_runner("matrix", run_matrix_client),
                name="mugen.platform.matrix",
            )
            task.add_done_callback(
                lambda done_task, platform_name="matrix": _on_platform_task_done(
                    platform_name, done_task
                )
            )
            tasks["matrix"] = task

        if "telnet" in active_platforms:
            logger.debug("Running telnet client.")
            task = asyncio.create_task(
                _invoke_platform_runner("telnet", run_telnet_client),
                name="mugen.platform.telnet",
            )
            task.add_done_callback(
                lambda done_task, platform_name="telnet": _on_platform_task_done(
                    platform_name, done_task
                )
            )
            tasks["telnet"] = task

        if "whatsapp" in active_platforms:
            logger.debug("Running whatsapp client.")
            task = asyncio.create_task(
                _invoke_platform_runner("whatsapp", run_whatsapp_client),
                name="mugen.platform.whatsapp",
            )
            task.add_done_callback(
                lambda done_task, platform_name="whatsapp": _on_platform_task_done(
                    platform_name, done_task
                )
            )
            tasks["whatsapp"] = task

        if "web" in active_platforms:
            logger.debug("Running web client.")
            task = asyncio.create_task(
                _invoke_platform_runner("web", run_web_client),
                name="mugen.platform.web",
            )
            task.add_done_callback(
                lambda done_task, platform_name="web": _on_platform_task_done(
                    platform_name, done_task
                )
            )
            tasks["web"] = task
    except AttributeError as exc:
        logger.error("Invalid platform configuration.")
        raise BootstrapConfigError("Invalid platform configuration.") from exc

    _refresh_phase_b_status(
        bootstrap_state,
        critical_platforms=critical_platforms,
        degrade_on_critical_exit=degrade_on_critical_exit,
    )

    if not tasks:
        return

    try:
        while tasks:
            done, _pending = await asyncio.wait(
                tuple(tasks.values()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for finished in done:
                for platform_name, platform_task in list(tasks.items()):
                    if platform_task is finished:
                        tasks.pop(platform_name, None)
                        break
    except asyncio.exceptions.CancelledError:
        bootstrap_state[SHUTDOWN_REQUESTED_KEY] = True
        for task in tasks.values():
            if task.done():
                continue
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise


async def register_extensions(  # pylint: disable=too-many-positional-arguments
    app: Quart,
    config_provider=_config_provider,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
    messaging_provider=_messaging_provider,
    platform_provider=_platform_provider,
) -> None:
    """Register core plugins and third party extensions."""
    config: SimpleNamespace = config_provider()
    ipc_service: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()
    messaging_service: IMessagingService = messaging_provider()
    platform_service: IPlatformService = platform_provider()

    # Load extensions if specified. These include:
    # 1. Command Processor (CP) extensions.
    # 2. Conversational Trigger (CT) extensions.
    # 3. Context (CTX) extensions.
    # 4. Framework (FW) extensions.
    # 5. Inter-Process Communication (IPC) extensions.
    # 6. Message Handler (MH) extensions.
    # 7. Retrieval Augmented Generation (RAG) extensions.
    # 8. Response Pre-Processor (RPP) extensions.
    extensions = []
    sweep_started_at = perf_counter()

    modules_config = getattr(
        getattr(config, "mugen", SimpleNamespace()),
        "modules",
        SimpleNamespace(),
    )
    core_modules_config = getattr(modules_config, "core", SimpleNamespace())

    plugins = getattr(core_modules_config, "plugins", [])
    if plugins is None:
        plugins = []
    if not isinstance(plugins, list):
        raise BootstrapConfigError(
            "Invalid extension configuration: mugen.modules.core.plugins must be a list."
        )
    if hasattr(core_modules_config, "plugins"):
        logger.debug("Adding plugins for loading.")
    else:
        logger.error("Plugin configuration attribute error.")
    extensions += plugins

    third_party_extensions = getattr(modules_config, "extensions", [])
    if third_party_extensions is None:
        third_party_extensions = []
    if not isinstance(third_party_extensions, list):
        raise BootstrapConfigError(
            "Invalid extension configuration: mugen.modules.extensions must be a list."
        )
    if hasattr(modules_config, "extensions"):
        logger.debug("Adding extensions for loading.")
    else:
        logger.error("Extension configuration attribute error.")
    extensions += third_party_extensions

    # Register core plugins and third party extensions.
    for ext in extensions:
        ext_started_at = perf_counter()
        ext_type = getattr(ext, "type", "<unknown>")
        ext_path = getattr(ext, "path", "<unknown>")
        if not _extension_enabled(ext):
            logger.info(f"Skipping disabled extension: {ext_path} ({ext_type}).")
            continue

        try:
            ext_module_name, ext_class_name = _split_extension_path(ext_path)
        except ValueError as exc:
            logger.error("Invalid extension path format.")
            logger.info(f"Module: {ext_path}.")
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(
                f"Invalid extension path format: {ext_path}."
            ) from exc

        # Flag used to signal that the plugin/extension
        # registration was successful.
        registered = False

        # Flag used to signal that the plugin/extension
        # platform is unsupported.
        extension_supported = False

        # Try importing the plugin/extension module.
        try:
            import_module(name=ext_module_name)
        except ModuleNotFoundError as exc:
            logger.error("Module import failed.")
            logger.info(f"Module: {ext_module_name}.")
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(f"Module import failed: {ext_module_name}.") from exc

        try:
            if ext_type == "cp":
                cp_ext_class = _resolve_extension_class(
                    interface=ICPExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                cp_ext = cp_ext_class()
                extension_supported = platform_service.extension_supported(cp_ext)
                if extension_supported:
                    messaging_service.register_cp_extension(cp_ext)
                    registered = True
            elif ext_type == "ct":
                ct_ext_class = _resolve_extension_class(
                    interface=ICTExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ct_ext = ct_ext_class()
                extension_supported = platform_service.extension_supported(ct_ext)
                if extension_supported:
                    messaging_service.register_ct_extension(ct_ext)
                    registered = True
            elif ext_type == "ctx":
                ctx_ext_class = _resolve_extension_class(
                    interface=ICTXExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ctx_ext = ctx_ext_class()
                extension_supported = platform_service.extension_supported(ctx_ext)
                if extension_supported:
                    messaging_service.register_ctx_extension(ctx_ext)
                    registered = True
            elif ext_type == "fw":
                fw_ext_class = _resolve_extension_class(
                    interface=IFWExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                fw_ext = fw_ext_class()
                extension_supported = platform_service.extension_supported(fw_ext)
                if extension_supported:
                    await fw_ext.setup(app)
                    registered = True
            elif ext_type == "ipc":
                ipc_ext_class = _resolve_extension_class(
                    interface=IIPCExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                ipc_ext = ipc_ext_class()
                extension_supported = platform_service.extension_supported(ipc_ext)
                if extension_supported:
                    ipc_service.register_ipc_extension(ipc_ext)
                    registered = True
            elif ext_type == "mh":
                mh_ext_class = _resolve_extension_class(
                    interface=IMHExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                mh_ext = mh_ext_class()
                extension_supported = platform_service.extension_supported(mh_ext)
                if extension_supported:
                    messaging_service.register_mh_extension(mh_ext)
                    registered = True
            elif ext_type == "rag":
                rag_ext_class = _resolve_extension_class(
                    interface=IRAGExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                rag_ext = rag_ext_class()
                extension_supported = platform_service.extension_supported(rag_ext)
                if extension_supported:
                    messaging_service.register_rag_extension(rag_ext)
                    registered = True
            elif ext_type == "rpp":
                rpp_ext_class = _resolve_extension_class(
                    interface=IRPPExtension,
                    module_name=ext_module_name,
                    class_name=ext_class_name,
                    ext_path=ext_path,
                )
                rpp_ext = rpp_ext_class()
                extension_supported = platform_service.extension_supported(rpp_ext)
                if extension_supported:
                    messaging_service.register_rpp_extension(rpp_ext)
                    registered = True
            else:
                logger.warning(f"Unknown extension type: {ext_type}.")
        except TypeError as exc:
            logger.exception(
                "Incomplete subclass implementation for extension: %s.",
                ext_path,
            )
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise ExtensionLoadError(
                f"Incomplete subclass implementation for extension: {ext_path}."
            ) from exc
        except ExtensionLoadError:
            logger.exception("Extension class resolution failed: %s.", ext_path)
            logger.error(
                "Extension bootstrap failed"
                f" type={ext_type} path={ext_path}"
                f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            raise

        if not extension_supported:
            logger.warning(f"Extension not supported by active platforms: {ext_path}.")

        if registered:
            logger.debug(f"Registered {ext_type.upper()} extension: {ext_path}.")

        logger.debug(
            "Extension bootstrap completed"
            f" type={ext_type} path={ext_path}"
            f" supported={extension_supported} registered={registered}"
            f" elapsed_seconds={perf_counter() - ext_started_at:.3f}"
        )

    logger.debug(
        "Extension bootstrap sweep completed"
        f" total_extensions={len(extensions)}"
        f" elapsed_seconds={perf_counter() - sweep_started_at:.3f}"
    )


async def run_telnet_client(
    logger_provider=_logger_provider,
    telnet_provider=_telnet_provider,
    started_callback=None,
) -> None:
    """Run assistant for Telnet server."""
    logger: ILoggingGateway = logger_provider()
    telnet_client: ITelnetClient = telnet_provider()

    async with telnet_client as client:
        try:
            await client.start_server(started_callback=started_callback)
            logger.debug("Telnet client started.")
        except asyncio.exceptions.CancelledError:
            logger.error("Telnet client shutting down.")
            raise


async def run_matrix_client(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    matrix_provider=_matrix_provider,
    started_callback=None,
) -> None:
    """Run assistant for the Matrix platform."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    matrix_client: IMatrixClient = matrix_provider()
    max_sync_retries = 5
    backoff_base_seconds = 1.0
    backoff_max_seconds = 30.0
    backoff_jitter_seconds = 0.25

    # Initialise matrix client.
    async with matrix_client as client:
        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_first_sync():

            # Wait for first sync to complete.
            await client.synced.wait()

            # Set profile name if it's not already set.
            profile = await client.get_profile()
            assistant_display_name = config.matrix.assistant.name
            if (
                assistant_display_name is not None
                and profile.displayname != assistant_display_name
            ):
                await client.set_displayname(assistant_display_name)

            # Cleanup device list and trust known devices.
            # matrix_client.cleanup_known_user_devices_list()
            await client.trust_known_user_devices()

            if callable(started_callback):
                started_callback()

        retry_attempt = 0
        while True:
            try:
                # Start process loop.
                await asyncio.gather(
                    asyncio.create_task(wait_on_first_sync()),
                    asyncio.create_task(
                        client.sync_forever(
                            since=client.sync_token,
                            timeout=100,
                            full_state=True,
                            set_presence="online",
                        )
                    ),
                    return_exceptions=False,
                )
                logger.debug("Matrix client started.")
                return
            except asyncio.exceptions.CancelledError:
                logger.error("Matrix client shutting down.")
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                is_auth_failure = (
                    re.search(
                        r"(m_unknown_token|unauthorized|forbidden|invalid token|access token)",
                        str(exc).lower(),
                    )
                    is not None
                )
                if is_auth_failure:
                    logger.error("Matrix client authentication failed; shutting down.")
                    raise RuntimeError("Matrix client authentication failed.") from exc

                if retry_attempt >= max_sync_retries:
                    logger.error("Matrix client sync failed after max retries.")
                    raise RuntimeError("Matrix client sync failed after max retries.") from exc

                delay_seconds = min(
                    backoff_max_seconds,
                    (backoff_base_seconds * (2**retry_attempt))
                    + random.uniform(0, backoff_jitter_seconds),
                )
                logger.warning(
                    "Matrix client sync error; retrying."
                    f" attempt={retry_attempt + 1}/{max_sync_retries}"
                    f" delay_seconds={delay_seconds:.2f}"
                    f" error={type(exc).__name__}: {exc}"
                )
                retry_attempt += 1
                await asyncio.sleep(delay_seconds)


async def run_whatsapp_client(
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
    started_callback=None,
) -> None:
    """Run assistant for the whatsapp platform."""
    logger: ILoggingGateway = logger_provider()
    whatsapp_client: IWhatsAppClient = whatsapp_provider()

    await whatsapp_client.init()
    try:
        startup_verified = await whatsapp_client.verify_startup()
        if startup_verified is not True:
            raise RuntimeError("WhatsApp startup probe failed.")
        if callable(started_callback):
            started_callback()
        logger.debug("WhatsApp client started.")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        logger.debug("WhatsApp client shutting down.")
        raise
    finally:
        try:
            await whatsapp_client.close()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Failed to close whatsapp client ({exc}).")


async def run_web_client(
    logger_provider=_logger_provider,
    web_provider=_web_provider,
    started_callback=None,
) -> None:
    """Run assistant for the web platform."""
    logger: ILoggingGateway = logger_provider()
    web_client: IWebClient = web_provider()

    await web_client.init()
    if callable(started_callback):
        started_callback()
    logger.debug("Web client started.")
    try:
        await web_client.wait_until_stopped()
    except asyncio.exceptions.CancelledError:
        logger.debug("Web client shutting down.")
        raise
    finally:
        try:
            await web_client.close()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Failed to close web client ({exc}).")
