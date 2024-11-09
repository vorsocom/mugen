"""Provides an implementation of INLPService."""

__all__ = ["DefaultNLPService"]

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.nlp import INLPService


class DefaultNLPService(INLPService):
    """An implementation of INLPService."""

    def __init__(self, logging_gateway: ILoggingGateway) -> None:
        self._logging_gateway = logging_gateway

    def get_keywords(self, text: str) -> list[str]:
        return []
