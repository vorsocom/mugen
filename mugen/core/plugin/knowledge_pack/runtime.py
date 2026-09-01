"""Holds runtime-only Knowledge Pack gateway services for ACP-bound actions."""

from __future__ import annotations

__all__ = ["configure_knowledge_gateway", "get_knowledge_gateway"]

from mugen.core.contract.gateway.knowledge import IKnowledgeGateway

_knowledge_gateway: IKnowledgeGateway | None = None


def configure_knowledge_gateway(gateway: IKnowledgeGateway | None) -> None:
    """Set the active projection gateway without making it an authoring source."""
    global _knowledge_gateway  # pylint: disable=global-statement
    _knowledge_gateway = gateway


def get_knowledge_gateway() -> IKnowledgeGateway | None:
    """Return the active projection gateway, if semantic search is configured."""
    return _knowledge_gateway
