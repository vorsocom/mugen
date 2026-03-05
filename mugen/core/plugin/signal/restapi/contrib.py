"""Signal REST API plugin contribution entrypoint."""

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
    """Contribute Signal REST API artifacts into `registry`."""
    _ = AdminNs(admin_namespace)
    _ = AdminNs(plugin_namespace)

    registry.register_table_spec(
        TableSpec(
            table_name="signal_restapi_event_dedup",
            table_provider=(
                "mugen.core.plugin.signal.restapi.model.event_dedup:"
                "SignalRestAPIEventDedup"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="signal_restapi_event_dead_letter",
            table_provider=(
                "mugen.core.plugin.signal.restapi.model.event_dead_letter:"
                "SignalRestAPIEventDeadLetter"
            ),
        )
    )
