"""Telegram Bot API plugin contribution entrypoint."""

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
    """Contribute Telegram Bot API artifacts into `registry`."""
    _ = AdminNs(admin_namespace)
    _ = AdminNs(plugin_namespace)

    registry.register_table_spec(
        TableSpec(
            table_name="telegram_botapi_event_dedup",
            table_provider=(
                "mugen.core.plugin.telegram.botapi.model.event_dedup:"
                "TelegramBotAPIEventDedup"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="telegram_botapi_event_dead_letter",
            table_provider=(
                "mugen.core.plugin.telegram.botapi.model.event_dead_letter:"
                "TelegramBotAPIEventDeadLetter"
            ),
        )
    )
