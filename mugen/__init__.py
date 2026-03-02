"""Quart application package."""

__all__ = [
    "BOOTSTRAP_STATE_KEY",
    "PHASE_A_CAPABILITY_ERRORS_KEY",
    "PHASE_A_CAPABILITY_STATUSES_KEY",
    "PHASE_A_ERROR_KEY",
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
    "run_web_client",
    "validate_web_relational_runtime_config",
    "validate_phase_b_runtime_config",
]

import asyncio
import inspect
import random
import re
from time import perf_counter
from types import SimpleNamespace

from quart import Quart

from mugen.bootstrap_state import (
    BOOTSTRAP_STATE_KEY,
    MUGEN_EXTENSION_KEY,
    PHASE_A_CAPABILITY_ERRORS_KEY,
    PHASE_A_CAPABILITY_STATUSES_KEY,
    PHASE_A_ERROR_KEY,
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
from mugen.core.bootstrap.extensions import (
    DefaultExtensionRegistry,
    configured_extensions,
    parse_bool as _parse_ext_bool,
    resolve_extension_spec,
)
from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.extension.registry import IExtensionRegistry
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.runtime.phase_b_bootstrap import (
    PHASE_B_CRITICAL_PLATFORMS_KEY as _PHASE_B_CRITICAL_PLATFORMS_KEY,
    PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY as _PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY,
    PhaseBStartupPlan,
)
from mugen.core.runtime.phase_b_coordinator import (
    prepare_phase_b_startup_plan,
    resolve_phase_b_startup_plan,
)
from mugen.core.runtime.phase_b_controls import (
    parse_bool as _parse_bool,
)
from mugen.core.runtime.phase_b_runtime import refresh_phase_b_health
from mugen.core.utility.platforms import (
    SUPPORTED_CORE_PLATFORMS,
    normalize_platforms,
    unknown_platforms,
)

_WHATSAPP_RUNTIME_PROBE_INTERVAL_SECONDS = 15.0


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


def _matrix_provider():
    return di.container.matrix_client


def _web_provider():
    return di.container.web_client


def _relational_storage_gateway_provider():
    return di.container.relational_storage_gateway


def _web_runtime_store_provider():
    return di.container.web_runtime_store


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
    web_runtime_store_provider=_web_runtime_store_provider,
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
        raise BootstrapConfigError(
            "Web platform requires relational storage gateway configuration at "
            "mugen.modules.core.gateway.storage.relational."
        )

    relational_storage_gateway = relational_storage_gateway_provider()
    if relational_storage_gateway is None:
        raise BootstrapConfigError(
            "Relational web storage is configured but "
            "relational_storage_gateway provider is unavailable."
        )

    relational_check_readiness = getattr(relational_storage_gateway, "check_readiness", None)
    if callable(relational_check_readiness) is not True:
        raise BootstrapConfigError(
            "Relational web storage is configured but "
            "relational_storage_gateway.check_readiness is unavailable."
        )

    web_runtime_configured = _config_path_exists(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "storage",
        "web_runtime",
    )
    if web_runtime_configured is not True:
        raise BootstrapConfigError(
            "Web platform requires web runtime store configuration at "
            "mugen.modules.core.gateway.storage.web_runtime."
        )

    web_runtime_store = web_runtime_store_provider()
    if web_runtime_store is None:
        raise BootstrapConfigError(
            "Web runtime store is configured but web_runtime_store provider is unavailable."
        )
    web_runtime_check_readiness = getattr(web_runtime_store, "check_readiness", None)
    if callable(web_runtime_check_readiness) is not True:
        raise BootstrapConfigError(
            "Web runtime store is configured but check_readiness is unavailable."
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


def _coerce_positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _coerce_positive_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _resolve_phase_b_supervision_controls(
    config: SimpleNamespace,
) -> tuple[int, float, float]:
    runtime_cfg = getattr(getattr(config, "mugen", SimpleNamespace()), "runtime", None)
    phase_b_cfg = getattr(runtime_cfg, "phase_b", None)
    max_restarts = _coerce_positive_int(
        getattr(phase_b_cfg, "supervisor_max_restarts", 3),
        default=3,
    )
    base_backoff_seconds = _coerce_positive_float(
        getattr(phase_b_cfg, "supervisor_backoff_base_seconds", 1.0),
        default=1.0,
    )
    max_backoff_seconds = _coerce_positive_float(
        getattr(phase_b_cfg, "supervisor_backoff_max_seconds", 30.0),
        default=30.0,
    )
    if max_backoff_seconds < base_backoff_seconds:
        max_backoff_seconds = base_backoff_seconds
    return max_restarts, base_backoff_seconds, max_backoff_seconds


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
    refresh_phase_b_health(
        bootstrap_state,
        critical_platforms=list(critical_platforms),
        degrade_on_critical_exit=degrade_on_critical_exit,
    )


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


async def bootstrap_app(
    app: Quart,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
) -> None:
    """Phase A bootstrap for app extensions and API registration."""
    logger: ILoggingGateway = logger_provider()
    bootstrap_state = get_bootstrap_state(app)
    capability_statuses = bootstrap_state.setdefault(PHASE_A_CAPABILITY_STATUSES_KEY, {})
    capability_errors = bootstrap_state.setdefault(PHASE_A_CAPABILITY_ERRORS_KEY, {})

    try:
        await di.ensure_container_readiness_async()
        capability_statuses["container_readiness"] = PHASE_STATUS_HEALTHY
        capability_errors["container_readiness"] = None
    except di.ProviderBootstrapError as exc:
        capability_statuses["container_readiness"] = PHASE_STATUS_DEGRADED
        capability_errors["container_readiness"] = str(exc)
        bootstrap_state[PHASE_A_ERROR_KEY] = str(exc)
        logger.warning(
            "Container readiness degraded; continuing startup in degraded mode "
            f"(error={exc})."
        )

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
    web_runtime_store_provider=_web_runtime_store_provider,
) -> None:
    """Phase B bootstrap for long-running platform clients."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    bootstrap_state = get_bootstrap_state(app)
    bootstrap_state[SHUTDOWN_REQUESTED_KEY] = False
    startup_plan: PhaseBStartupPlan = resolve_phase_b_startup_plan(
        config=config,
        bootstrap_state=bootstrap_state,
        logger=logger,
        validate_phase_b_runtime_config=validate_phase_b_runtime_config,
        validate_web_relational_runtime_config=lambda **kwargs: (
            validate_web_relational_runtime_config(
                **kwargs,
                relational_storage_gateway_provider=(
                    relational_storage_gateway_provider
                ),
                web_runtime_store_provider=web_runtime_store_provider,
            )
        ),
    )

    active_platforms = list(startup_plan.active_platforms)
    critical_platforms = list(startup_plan.critical_platforms)
    degrade_on_critical_exit = bool(startup_plan.degrade_on_critical_exit)

    _ensure_platform_state(
        bootstrap_state,
        active_platforms=active_platforms,
    )

    tasks: dict[str, asyncio.Task] = {}

    def _on_platform_started(platform_name: str) -> None:
        _on_platform_healthy(platform_name)

    def _on_platform_healthy(platform_name: str) -> None:
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

    def _on_platform_degraded(
        platform_name: str,
        reason: str | None = None,
    ) -> None:
        shutdown_requested = _parse_bool(
            bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
            default=False,
        )
        if shutdown_requested:
            return

        normalized_reason = reason
        if isinstance(normalized_reason, str):
            normalized_reason = normalized_reason.strip()
        if normalized_reason in [None, ""]:
            normalized_reason = "runtime health check failed"

        _set_platform_status(
            bootstrap_state,
            platform=platform_name,
            status=PHASE_STATUS_DEGRADED,
            error=str(normalized_reason),
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

        def _degraded_callback(reason: str | None = None) -> None:
            _on_platform_degraded(platform_name, reason=reason)

        def _healthy_callback() -> None:
            _on_platform_healthy(platform_name)

        try:
            return runner(
                started_callback=_started_callback,
                degraded_callback=_degraded_callback,
                healthy_callback=_healthy_callback,
            )
        except TypeError as exc:
            exc_text = str(exc)
            callback_name = next(
                (
                    callback
                    for callback in (
                        "started_callback",
                        "degraded_callback",
                        "healthy_callback",
                    )
                    if callback in exc_text
                ),
                None,
            )
            if callback_name is None:
                raise

            async def _signature_mismatch_runner(
                captured_exc: TypeError = exc,
                mismatched_callback: str = callback_name,
            ) -> None:
                raise RuntimeError(
                    f"{platform_name} runner does not accept required callback "
                    f"parameter '{mismatched_callback}'."
                ) from captured_exc

            return _signature_mismatch_runner()

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
            else:
                _set_platform_status(
                    bootstrap_state,
                    platform=platform_name,
                    status=PHASE_STATUS_DEGRADED,
                    error="platform runner stopped unexpectedly",
                )
                logger.error(
                    f"{platform_name} client stopped unexpectedly without exception."
                )
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

    (
        supervisor_max_restarts,
        supervisor_backoff_base_seconds,
        supervisor_backoff_max_seconds,
    ) = _resolve_phase_b_supervision_controls(config)

    async def _supervise_platform_runner(platform_name: str, runner) -> None:
        restart_count = 0
        last_error_message: str | None = None
        while True:
            shutdown_requested = _parse_bool(
                bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
                default=False,
            )
            if shutdown_requested:
                return
            try:
                await _invoke_platform_runner(platform_name, runner)
                shutdown_requested = _parse_bool(
                    bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
                    default=False,
                )
                if shutdown_requested:
                    return
                last_error_message = "platform runner exited unexpectedly"
                _on_platform_degraded(platform_name, last_error_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_error_message = f"{type(exc).__name__}: {exc}"
                _on_platform_degraded(platform_name, last_error_message)

            if restart_count >= supervisor_max_restarts:
                raise RuntimeError(
                    f"{platform_name} runner exhausted restart budget "
                    f"({supervisor_max_restarts}) after last error: "
                    f"{last_error_message or 'unknown failure'}."
                )
            backoff_seconds = min(
                supervisor_backoff_max_seconds,
                supervisor_backoff_base_seconds * (2**restart_count),
            )
            logger.warning(
                f"{platform_name} runner restart scheduled "
                f"attempt={restart_count + 1}/{supervisor_max_restarts} "
                f"backoff_seconds={backoff_seconds:.2f}."
            )
            restart_count += 1
            await asyncio.sleep(backoff_seconds)

    try:
        if "matrix" in active_platforms:
            logger.debug("Running matrix client.")
            task = asyncio.create_task(
                _supervise_platform_runner("matrix", run_matrix_client),
                name="mugen.platform.matrix",
            )
            task.add_done_callback(
                lambda done_task, platform_name="matrix": _on_platform_task_done(
                    platform_name, done_task
                )
            )
            tasks["matrix"] = task

        if "whatsapp" in active_platforms:
            logger.debug("Running whatsapp client.")
            task = asyncio.create_task(
                _supervise_platform_runner("whatsapp", run_whatsapp_client),
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
                _supervise_platform_runner("web", run_web_client),
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
            if task.done():  # pragma: no cover
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
    extension_registry_provider=None,
) -> None:
    """Register core plugins and third party extensions."""
    config: SimpleNamespace = config_provider()
    ipc_service: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()
    messaging_service: IMessagingService = messaging_provider()
    platform_service: IPlatformService = platform_provider()
    sweep_started_at = perf_counter()
    try:
        extensions = configured_extensions(config)
    except RuntimeError as exc:
        raise BootstrapConfigError(str(exc)) from exc

    if extension_registry_provider is None:
        extension_registry: IExtensionRegistry = DefaultExtensionRegistry(
            messaging_service=messaging_service,
            ipc_service=ipc_service,
            platform_service=platform_service,
            logging_gateway=logger,
        )
    else:
        extension_registry = extension_registry_provider()

    for ext_cfg in extensions:
        ext_started_at = perf_counter()
        raw_token = getattr(ext_cfg, "token", None)
        legacy_path = getattr(ext_cfg, "path", None)
        if raw_token is None and legacy_path is not None:
            raise ExtensionLoadError(
                "Legacy extension path configuration is no longer supported. "
                "Use token-based extension loading."
            )
        token = str(raw_token or "").strip().lower()
        configured_type = str(getattr(ext_cfg, "type", "") or "").strip().lower()
        critical = _parse_ext_bool(getattr(ext_cfg, "critical", False), default=False)

        if not _extension_enabled(ext_cfg):
            logger.info(
                f"Skipping disabled extension: {token or '<unknown>'}"
                f" ({configured_type or '<unknown>'})."
            )
            continue

        try:
            spec = resolve_extension_spec(token)
            resolved_type = spec.extension_type
            if configured_type not in {"", resolved_type}:
                raise ExtensionLoadError(
                    "Extension type/token mismatch "
                    f"(token={token} configured_type={configured_type} "
                    f"resolved_type={resolved_type})."
                )
            extension = spec.extension_class()
            registered = await extension_registry.register(
                app=app,
                extension_type=resolved_type,
                extension=extension,
                token=token,
                critical=critical,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if critical:
                logger.error(
                    "Critical extension bootstrap failed "
                    f"token={token} elapsed_seconds={perf_counter() - ext_started_at:.3f}"
                )
                if isinstance(exc, ExtensionLoadError):
                    raise
                raise ExtensionLoadError(
                    f"Critical extension failed: {token}."
                ) from exc

            logger.warning(
                "Non-critical extension bootstrap failed "
                f"token={token} error_type={type(exc).__name__} error={exc} "
                f"elapsed_seconds={perf_counter() - ext_started_at:.3f}"
            )
            continue

        if registered:
            logger.debug(
                f"Registered {resolved_type.upper()} extension: {token}."
            )
        else:
            logger.debug(
                f"Skipped unsupported extension: {token} ({resolved_type})."
            )

    logger.debug(
        "Extension bootstrap sweep completed"
        f" total_extensions={len(extensions)}"
        f" elapsed_seconds={perf_counter() - sweep_started_at:.3f}"
    )


async def run_matrix_client(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    matrix_provider=_matrix_provider,
    started_callback=None,
    degraded_callback=None,
    healthy_callback=None,
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
        started_signalled = False
        runtime_degraded = False
        consecutive_sync_failures = 0

        # We have to wait on the first sync event to perform some setup tasks.
        async def wait_on_sync_ready():
            nonlocal started_signalled
            nonlocal runtime_degraded
            nonlocal consecutive_sync_failures

            # Wait for a fresh sync to complete.
            await client.synced.wait()
            consecutive_sync_failures = 0

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

            if started_signalled is not True:
                if callable(started_callback):
                    started_callback()
                if callable(healthy_callback):
                    healthy_callback()
                started_signalled = True
                runtime_degraded = False
                return

            if runtime_degraded is True and callable(healthy_callback):
                healthy_callback()
            runtime_degraded = False

        while True:
            try:
                synced_signal = getattr(client, "synced", None)
                clear_sync_signal = getattr(synced_signal, "clear", None)
                if callable(clear_sync_signal):
                    clear_result = clear_sync_signal()
                    if inspect.isawaitable(clear_result):
                        await clear_result

                # Start process loop.
                await asyncio.gather(
                    asyncio.create_task(wait_on_sync_ready()),
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

                if consecutive_sync_failures >= max_sync_retries:
                    logger.error("Matrix client sync failed after max retries.")
                    raise RuntimeError("Matrix client sync failed after max retries.") from exc

                if runtime_degraded is not True and callable(degraded_callback):
                    degraded_callback(f"{type(exc).__name__}: {exc}")
                runtime_degraded = True

                delay_seconds = min(
                    backoff_max_seconds,
                    (backoff_base_seconds * (2**consecutive_sync_failures))
                    + random.uniform(0, backoff_jitter_seconds),
                )
                logger.warning(
                    "Matrix client sync error; retrying."
                    f" attempt={consecutive_sync_failures + 1}/{max_sync_retries}"
                    f" delay_seconds={delay_seconds:.2f}"
                    f" error={type(exc).__name__}: {exc}"
                )
                consecutive_sync_failures += 1
                await asyncio.sleep(delay_seconds)


async def run_whatsapp_client(
    logger_provider=_logger_provider,
    whatsapp_provider=_whatsapp_provider,
    started_callback=None,
    degraded_callback=None,
    healthy_callback=None,
) -> None:
    """Run assistant for the whatsapp platform."""
    logger: ILoggingGateway = logger_provider()
    whatsapp_client: IWhatsAppClient = whatsapp_provider()

    try:
        await whatsapp_client.init()
        startup_verified = await whatsapp_client.verify_startup()
        if startup_verified is not True:
            raise RuntimeError("WhatsApp startup probe failed.")
        if callable(started_callback):
            started_callback()
        if callable(healthy_callback):
            healthy_callback()
        logger.debug("WhatsApp client started.")
        runtime_degraded = False
        while True:
            await asyncio.sleep(_WHATSAPP_RUNTIME_PROBE_INTERVAL_SECONDS)
            try:
                runtime_probe_ok = await whatsapp_client.verify_startup()
            except asyncio.exceptions.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "WhatsApp runtime probe failed "
                    f"(error_type={type(exc).__name__} error={exc})."
                )
                if runtime_degraded is not True and callable(degraded_callback):
                    degraded_callback(f"{type(exc).__name__}: {exc}")
                runtime_degraded = True
                continue

            if runtime_probe_ok is True:
                if runtime_degraded is True and callable(healthy_callback):
                    healthy_callback()
                runtime_degraded = False
                continue

            logger.warning("WhatsApp runtime probe returned unhealthy status.")
            if runtime_degraded is not True and callable(degraded_callback):
                degraded_callback("WhatsApp runtime startup probe failed.")
            runtime_degraded = True
    except asyncio.exceptions.CancelledError:
        logger.debug("WhatsApp client shutting down.")
        raise
    except Exception as exc:
        if callable(degraded_callback):
            degraded_callback(f"{type(exc).__name__}: {exc}")
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
    degraded_callback=None,
    healthy_callback=None,
) -> None:
    """Run assistant for the web platform."""
    logger: ILoggingGateway = logger_provider()
    web_client: IWebClient = web_provider()
    try:
        await web_client.init()
    except Exception as exc:
        if callable(degraded_callback):
            degraded_callback(f"{type(exc).__name__}: {exc}")
        raise

    if callable(started_callback):
        started_callback()
    if callable(healthy_callback):
        healthy_callback()
    logger.debug("Web client started.")

    try:
        await web_client.wait_until_stopped()
    except asyncio.exceptions.CancelledError:
        logger.debug("Web client shutting down.")
        raise
    except Exception as exc:
        if callable(degraded_callback):
            degraded_callback(f"{type(exc).__name__}: {exc}")
        raise
    else:
        if callable(degraded_callback):
            degraded_callback("Web client stopped.")
    finally:
        try:
            await web_client.close()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Failed to close web client ({exc}).")
