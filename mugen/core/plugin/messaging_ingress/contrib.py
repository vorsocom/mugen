"""Shared messaging ingress ACP table contributions."""

from mugen.core.plugin.acp.contract.sdk.binding import TableSpec
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry


def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute shared messaging ingress reliability tables."""
    _ = admin_namespace, plugin_namespace
    registry.register_table_spec(
        TableSpec(
            table_name="messaging_ingress_event",
            table_provider=(
                "mugen.core.plugin.messaging_ingress.model.event:"
                "MessagingIngressEventRecord"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="messaging_ingress_dedup",
            table_provider=(
                "mugen.core.plugin.messaging_ingress.model.dedup:"
                "MessagingIngressDedupRecord"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="messaging_ingress_dead_letter",
            table_provider=(
                "mugen.core.plugin.messaging_ingress.model.dead_letter:"
                "MessagingIngressDeadLetterRecord"
            ),
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="messaging_ingress_checkpoint",
            table_provider=(
                "mugen.core.plugin.messaging_ingress.model.checkpoint:"
                "MessagingIngressCheckpointRecord"
            ),
        )
    )
