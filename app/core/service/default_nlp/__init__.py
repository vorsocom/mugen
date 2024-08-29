"""Provides an implementation of INLPService."""

__all__ = ["DefaultNLPService"]

from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.nlp_service import INLPService
from app.core.service.default_nlp.keyword_extractor import (
    CustomKeywordExtractor,
)


class DefaultNLPService(INLPService):
    """An implementation of INLPService."""

    def __init__(self, logging_gateway: ILoggingGateway) -> None:
        self._logging_gateway = logging_gateway
        self._kwe = CustomKeywordExtractor(top=5)

    def get_keywords(self, text: str) -> list[str]:
        keywords = self._kwe.extract_keywords(text)
        return [kw[0] for kw in keywords]
