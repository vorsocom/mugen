"""LINE Messaging API plugin contribution entrypoint."""

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.binding import TableSpec
from mugen.core.plugin.acp.utility.ns import AdminNs


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute LINE Messaging API artifacts into `registry`."""
    _ = AdminNs(admin_namespace)
    _ = AdminNs(plugin_namespace)

    registry.register_table_spec(
        TableSpec(
            table_name="line_messagingapi_event_dedup",
            table_provider=(
                "mugen.core.plugin.line.messagingapi.model.event_dedup:"
                "LineMessagingAPIEventDedup"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="line_messagingapi_event_dead_letter",
            table_provider=(
                "mugen.core.plugin.line.messagingapi.model.event_dead_letter:"
                "LineMessagingAPIEventDeadLetter"
            ),
        )
    )
