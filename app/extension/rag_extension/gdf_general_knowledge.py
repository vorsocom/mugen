"""Provides an implementation of IRAGExtension."""

__all__ = ["GDFGeneralKnowldgeRAGExtension"]

import json
import pickle
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide
from qdrant_client.models import ScoredPoint

from app.core.contract.rag_extension import IRAGExtension
from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.user_service import IUserService

from app.core.di import DIContainer


class GDFGeneralKnowldgeRAGExtension(IRAGExtension):
    """An implementation of IRAGExtension."""

    _cache_key: str = "rag_cache_gdf_general_knowledge"

    # pylint: disable=too-many-arguments
    @inject
    def __init__(
        self,
        completion_gateway: ICompletionGateway = Provide[
            DIContainer.completion_gateway
        ],
        config: dict = Provide[DIContainer.config],
        keyval_storage_gateway: IKeyValStorageGateway = Provide[
            DIContainer.keyval_storage_gateway
        ],
        knowledge_retrieval_gateway: IKnowledgeRetrievalGateway = Provide[
            DIContainer.knowledge_retrieval_gateway
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
        user_service: IUserService = Provide[DIContainer.user_service],
    ) -> None:
        self._completion_gateway = completion_gateway
        self._config = SimpleNamespace(**config)
        self._keyval_storage_gateway = keyval_storage_gateway
        self._knowledge_retrieval_gateway = knowledge_retrieval_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

        # Configure completion API.
        completion_api_prefix = self._config.gloria_completion_api_prefix
        classification_model = f"{completion_api_prefix}_api_classification_model"
        self._classification_model = config[classification_model]
        classification_temp = f"{completion_api_prefix}_api_classification_temp"
        self._classification_temp = config[classification_temp]
        completion_model = f"{completion_api_prefix}_api_completion_model"
        self._completion_model = config[completion_model]
        completion_temp = f"{completion_api_prefix}_api_completion_temp"
        self._completion_temp = config[completion_temp]

    @property
    def cache_key(self) -> str:
        return self._cache_key

    async def retrieve(self, sender: str, message: str) -> None:
        self._logging_gateway.debug("Processing GDF Knowledge RAG pipeline.")
        gdfk_classification = await self._get_rag_classification(
            message=message,
            model=self._classification_model,
            temperature=float(self._classification_temp),
        )

        knowledge_docs: list[str] = []
        if gdfk_classification is not None:
            self._logging_gateway.debug(gdfk_classification)
            instruct = json.loads(gdfk_classification.content)
            if instruct["classification"]:
                hits: list[ScoredPoint] = (
                    await self._knowledge_retrieval_gateway.search_similar(
                        "guyana_defence_force", "gdf_knowledge", message, "should"
                    )
                )
                if len(hits) > 0:
                    self._logging_gateway.debug(
                        "default_messaging_gateway: similarity search hits -"
                        f" {len(hits)}"
                    )
                    for hit in hits:
                        if "source" in hit.payload.keys():
                            knowledge_docs.append(
                                f'Section {hit.payload["section"]} of'
                                f' {hit.payload["chapter"]} of the'
                                f' {hit.payload["source"]} states:'
                                f' {hit.payload["data"]}'
                            )
                        else:
                            knowledge_docs.append(hit.payload["data"])

                # self._logging_gateway.debug(f"default_messaging_service: RAG {knowledge_docs}")

                if len(knowledge_docs) == 0:
                    knowledge_docs.append(
                        "No relevant information found in your GDF knowledge base. Do"
                        " not make up any information."
                    )

                context = []
                context.append(
                    {
                        "role": "system",
                        "content": " || ".join(knowledge_docs),
                    }
                )
                self._keyval_storage_gateway.put(self._cache_key, pickle.dumps(context))

    async def _get_rag_classification(
        self,
        message: str,
        model: str,
        temperature: float,
        response_format: str = "json_object",
    ) -> str | None:
        """Classify user messages for GDF Knowledge RAG pipeline."""
        context = [
            {
                "role": "system",
                "content": (
                    "You are a message classifier. You classify user messages and"
                    " return valid JSON based on your classification. Do not return"
                    " anything but JSON. In this instance you are classifying messages"
                    " based on whether the user wants information related to the Guyana"
                    " Defence Force (GDF) or not. A positive classification is when the"
                    " user wants information related to the GDF. A negative"
                    " classification is when the user does not want information related"
                    " to the GDF. For a positive classification, the user needs to"
                    ' mention "Guyana Defence Force", "GDF", or "Force". For a positive'
                    ' classification, return {"classification": true}. For a negative'
                    ' classification, return {"classification": false}. Your response'
                    " should not contain any text other than the JSON string."
                ),
            },
            {"role": "user", "content": message},
        ]
        return await self._completion_gateway.get_completion(
            context=context,
            model=model,
            response_format=response_format,
            temperature=temperature,
        )
