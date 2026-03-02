"""Extension bootstrap registry and token resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.registry import IExtensionRegistry
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.platform import IPlatformService

_KNOWN_EXTENSION_TYPES = {"cp", "ct", "ctx", "fw", "ipc", "mh", "rag", "rpp"}


def parse_bool(value: object, *, default: bool) -> bool:
    """Parse bool-like values with deterministic defaults."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class ExtensionTokenSpec:
    """Resolved extension token metadata."""

    extension_type: str
    interface: type
    extension_class: type


@dataclass(frozen=True)
class _ExtensionClassRef:
    extension_type: str
    interface: type
    module_path: str
    class_name: str


_EXTENSION_TOKEN_REGISTRY: dict[str, _ExtensionClassRef] = {
    "core.fw.acp": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.acp.fw_ext", "AdminFWExtension"),
    "core.fw.audit": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.audit.fw_ext", "AuditFWExtension"),
    "core.fw.ops_vpn": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_vpn.fw_ext", "OpsVpnFWExtension"),
    "core.fw.ops_case": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_case.fw_ext", "OpsCaseFWExtension"),
    "core.fw.ops_sla": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_sla.fw_ext", "OpsSlaFWExtension"),
    "core.fw.ops_metering": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_metering.fw_ext", "OpsMeteringFWExtension"),
    "core.fw.ops_workflow": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_workflow.fw_ext", "OpsWorkflowFWExtension"),
    "core.fw.ops_governance": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_governance.fw_ext", "OpsGovernanceFWExtension"),
    "core.fw.ops_reporting": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_reporting.fw_ext", "OpsReportingFWExtension"),
    "core.fw.ops_connector": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.ops_connector.fw_ext", "OpsConnectorFWExtension"),
    "core.fw.billing": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.billing.fw_ext", "BillingFWExtension"),
    "core.fw.knowledge_pack": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.knowledge_pack.fw_ext", "KnowledgePackFWExtension"),
    "core.fw.channel_orchestration": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.channel_orchestration.fw_ext", "ChannelOrchestrationFWExtension"),
    "core.fw.whatsapp_wacapi": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.whatsapp.wacapi.fw_ext", "WACAPIFWExtension"),
    "core.fw.web": _ExtensionClassRef("fw", IFWExtension, "mugen.core.plugin.web.fw_ext", "WebFWExtension"),
    "core.ipc.whatsapp_wacapi": _ExtensionClassRef("ipc", IIPCExtension, "mugen.core.plugin.whatsapp.wacapi.ipc_ext", "WhatsAppWACAPIIPCExtension"),
    "core.ipc.matrix_room_management": _ExtensionClassRef("ipc", IIPCExtension, "mugen.core.plugin.matrix.manager.room_ipc_ext", "RoomManagementIPCExtension"),
    "core.ipc.matrix_device_management": _ExtensionClassRef("ipc", IIPCExtension, "mugen.core.plugin.matrix.manager.device_ipc_ext", "DeviceManagementIPCExtension"),
    "core.ctx.system_persona": _ExtensionClassRef("ctx", ICTXExtension, "mugen.core.plugin.context.persona.ctx_ext", "SystemPersonaCTXExtension"),
    "core.cp.clear_history": _ExtensionClassRef("cp", ICPExtension, "mugen.core.plugin.command.clear_history.cp_ext", "ClearChatHistoryICPExtension"),
    "core.mh.default_text": _ExtensionClassRef("mh", IMHExtension, "mugen.core.plugin.message_handler.text.mh_ext", "DefaultTextMHExtension"),
}


def resolve_extension_spec(token: object) -> ExtensionTokenSpec:
    """Resolve extension token to explicit class/interface metadata."""
    if not isinstance(token, str):
        raise RuntimeError("Invalid extension token: expected a string.")
    normalized = token.strip().lower()
    if normalized == "":
        raise RuntimeError("Invalid extension token: token must be non-empty.")
    if ":" in normalized:
        raise RuntimeError("Invalid extension token: module:Class paths are not supported.")

    class_ref = _EXTENSION_TOKEN_REGISTRY.get(normalized)
    if class_ref is None:
        known_tokens = ", ".join(sorted(_EXTENSION_TOKEN_REGISTRY.keys()))
        raise RuntimeError(
            f"Unknown extension token: {token!r}. Known tokens: {known_tokens}."
        )
    try:
        module = importlib.import_module(class_ref.module_path)
        extension_class = getattr(module, class_ref.class_name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(
            f"Invalid extension class binding for token: {token!r}."
        ) from exc
    if not isinstance(extension_class, type):
        raise RuntimeError(f"Invalid extension class binding for token: {token!r}.")
    if not issubclass(extension_class, class_ref.interface):
        raise RuntimeError(f"Invalid extension class binding for token: {token!r}.")
    return ExtensionTokenSpec(
        extension_type=class_ref.extension_type,
        interface=class_ref.interface,
        extension_class=extension_class,
    )


class DefaultExtensionRegistry(IExtensionRegistry):
    """Core extension registration coordinator."""

    def __init__(
        self,
        *,
        messaging_service: IMessagingService,
        ipc_service: IIPCService,
        platform_service: IPlatformService,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._messaging_service = messaging_service
        self._ipc_service = ipc_service
        self._platform_service = platform_service
        self._logging_gateway = logging_gateway

    async def register(
        self,
        *,
        app: Any,
        extension_type: str,
        extension,
        token: str,
        critical: bool,
    ) -> bool:
        ext_type = str(extension_type).strip().lower()
        if ext_type not in _KNOWN_EXTENSION_TYPES:
            raise RuntimeError(f"Unknown extension type: {extension_type!r}.")
        if self._platform_service.extension_supported(extension) is not True:
            self._logging_gateway.warning(
                f"Extension not supported by active platforms: {token}."
            )
            return False

        if ext_type == "fw":
            await extension.setup(app)
            return True
        if ext_type == "ipc":
            self._bind_ipc_extension(extension=extension, critical=critical)
            return True
        self._bind_messaging_extension(
            extension_type=ext_type,
            extension=extension,
            critical=critical,
        )
        return True

    def _bind_ipc_extension(
        self,
        *,
        extension: IIPCExtension,
        critical: bool,
    ) -> None:
        self._ipc_service.bind_ipc_extension(extension, critical=critical)

    def _bind_messaging_extension(
        self,
        *,
        extension_type: str,
        extension,
        critical: bool,
    ) -> None:
        if extension_type == "cp":
            self._messaging_service.bind_cp_extension(extension, critical=critical)
            return
        if extension_type == "ct":
            self._messaging_service.bind_ct_extension(extension, critical=critical)
            return
        if extension_type == "ctx":
            self._messaging_service.bind_ctx_extension(extension, critical=critical)
            return
        if extension_type == "mh":
            self._messaging_service.bind_mh_extension(extension, critical=critical)
            return
        if extension_type == "rag":
            self._messaging_service.bind_rag_extension(extension, critical=critical)
            return
        if extension_type == "rpp":
            self._messaging_service.bind_rpp_extension(extension, critical=critical)
            return
        raise RuntimeError(
            f"Messaging extension binding is unavailable for type {extension_type!r}."
        )


def configured_extensions(config: SimpleNamespace) -> list[SimpleNamespace]:
    """Return merged core and downstream extension configuration rows."""
    modules_config = getattr(
        getattr(config, "mugen", SimpleNamespace()),
        "modules",
        SimpleNamespace(),
    )
    core_modules_config = getattr(modules_config, "core", SimpleNamespace())

    merged: list[SimpleNamespace] = []
    core_plugins = getattr(core_modules_config, "plugins", [])
    if core_plugins is None:
        core_plugins = []
    if not isinstance(core_plugins, list):
        raise RuntimeError(
            "Invalid extension configuration: mugen.modules.core.plugins must be a list."
        )
    merged += list(core_plugins)

    downstream_extensions = getattr(modules_config, "extensions", [])
    if downstream_extensions is None:
        downstream_extensions = []
    if not isinstance(downstream_extensions, list):
        raise RuntimeError(
            "Invalid extension configuration: mugen.modules.extensions must be a list."
        )
    merged += list(downstream_extensions)
    return merged
