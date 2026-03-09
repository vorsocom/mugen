"""Unified extension token registry."""

from __future__ import annotations

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension


def get_plugin_extension_token_registry() -> dict[str, tuple[str, type, str, str]]:
    """Return extension token bindings for unified config entries."""
    return {
        "core.cp.clear_history": (
            "cp",
            ICPExtension,
            "mugen.core.extension.cp.clear_history",
            "ClearChatHistoryICPExtension",
        ),
        "core.fw.acp": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.acp.fw_ext",
            "AdminFWExtension",
        ),
        "core.fw.audit": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.audit.fw_ext",
            "AuditFWExtension",
        ),
        "core.fw.context_engine": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.context_engine.fw_ext",
            "ContextEngineFWExtension",
        ),
        "core.fw.ops_vpn": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_vpn.fw_ext",
            "OpsVpnFWExtension",
        ),
        "core.fw.ops_case": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_case.fw_ext",
            "OpsCaseFWExtension",
        ),
        "core.fw.ops_sla": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_sla.fw_ext",
            "OpsSlaFWExtension",
        ),
        "core.fw.ops_metering": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_metering.fw_ext",
            "OpsMeteringFWExtension",
        ),
        "core.fw.ops_workflow": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_workflow.fw_ext",
            "OpsWorkflowFWExtension",
        ),
        "core.fw.ops_governance": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_governance.fw_ext",
            "OpsGovernanceFWExtension",
        ),
        "core.fw.ops_reporting": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_reporting.fw_ext",
            "OpsReportingFWExtension",
        ),
        "core.fw.ops_connector": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.ops_connector.fw_ext",
            "OpsConnectorFWExtension",
        ),
        "core.fw.billing": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.billing.fw_ext",
            "BillingFWExtension",
        ),
        "core.fw.knowledge_pack": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.knowledge_pack.fw_ext",
            "KnowledgePackFWExtension",
        ),
        "core.fw.channel_orchestration": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.channel_orchestration.fw_ext",
            "ChannelOrchestrationFWExtension",
        ),
        "core.fw.whatsapp_wacapi": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.whatsapp.wacapi.fw_ext",
            "WACAPIFWExtension",
        ),
        "core.fw.line_messagingapi": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.line.messagingapi.fw_ext",
            "LineMessagingAPIFWExtension",
        ),
        "core.fw.telegram_botapi": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.telegram.botapi.fw_ext",
            "TelegramBotAPIFWExtension",
        ),
        "core.fw.wechat": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.wechat.fw_ext",
            "WeChatFWExtension",
        ),
        "core.fw.web": (
            "fw",
            IFWExtension,
            "mugen.core.plugin.web.fw_ext",
            "WebFWExtension",
        ),
        "core.ipc.whatsapp_wacapi": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.whatsapp.wacapi.ipc_ext",
            "WhatsAppWACAPIIPCExtension",
        ),
        "core.ipc.line_messagingapi": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.line.messagingapi.ipc_ext",
            "LineMessagingAPIIPCExtension",
        ),
        "core.ipc.signal_restapi": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.signal.restapi.ipc_ext",
            "SignalRestAPIIPCExtension",
        ),
        "core.ipc.telegram_botapi": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.telegram.botapi.ipc_ext",
            "TelegramBotAPIIPCExtension",
        ),
        "core.ipc.wechat": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.wechat.ipc_ext",
            "WeChatIPCExtension",
        ),
        "core.ipc.matrix_room_management": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.matrix.manager.room_ipc_ext",
            "RoomManagementIPCExtension",
        ),
        "core.ipc.matrix_device_management": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.matrix.manager.device_ipc_ext",
            "DeviceManagementIPCExtension",
        ),
        "core.ipc.matrix_ingress": (
            "ipc",
            IIPCExtension,
            "mugen.core.plugin.matrix.ingress_ipc_ext",
            "MatrixIngressIPCExtension",
        ),
    }
