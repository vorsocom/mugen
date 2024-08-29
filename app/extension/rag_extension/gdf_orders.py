"""Provides an implementation of IRAGExtension."""

__all__ = ["GDFOrdersRAGExtension"]

import json
import pickle
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide

from app.core.contract.rag_extension import IRAGExtension
from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.user_service import IUserService
from app.core.di import DIContainer


# pylint: disable=too-few-public-methods
class GDFOrdersRAGExtension(IRAGExtension):
    """An implementation of IRAGExtension."""

    _cache_key: str = "rag_cache_gdf_orders"

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
        self._logging_gateway.debug("Processing Orders RAG pipeline.")
        user_dn = self._user_service.get_user_display_name(sender)
        orders_classification = await self._get_rag_classification(
            user=user_dn,
            message=message,
            model=self._classification_model,
            temperature=float(self._classification_temp),
        )

        knowledge_docs: list[str] = []
        if orders_classification is not None:
            self._logging_gateway.debug(orders_classification)
            instruct = json.loads(orders_classification.content)
            if instruct["classification"]:
                hits = await self._knowledge_retrieval_gateway.search_similar(
                    "guyana_defence_force",
                    "orders",
                    f'{instruct["subject"]} {instruct["event_type"]}',
                )
                if len(hits) > 0:
                    self._logging_gateway.debug(
                        "default_messaging_gateway: similarity search hits -"
                        f" {len(hits)}"
                    )
                    hit_str = (
                        "In {0} Orders Serial {1} dated {2}, paragraph {3} states: {4}"
                    )
                    knowledge_docs = [
                        hit_str.format(
                            x.payload["type"],
                            x.payload["serial"],
                            x.payload["date"],
                            x.payload["paragraph"],
                            x.payload["data"],
                        )
                        for x in hits
                    ]

                # self._logging_gateway.debug(f"default_messaging_service: RAG {knowledge_docs}")

                if len(knowledge_docs) == 0:
                    knowledge_docs.append(
                        "No relevant information found in your orders search. Do not"
                        " make up any information."
                    )

                context = []
                context.append(
                    {
                        "role": "system",
                        "content": " || ".join(knowledge_docs),
                    }
                )
                context.append(
                    {
                        "role": "system",
                        "content": (
                            "When giving information from orders, always cite the"
                            " serial, paragraph number, and date of publication."
                        ),
                    }
                )
                self._keyval_storage_gateway.put(self._cache_key, pickle.dumps(context))

    async def _get_rag_classification(
        self,
        user: str,
        message: str,
        model: str,
        temperature: float,
        response_format: str = "json_object",
    ) -> str | None:
        """Classify user messages for orders RAG pipeline."""
        context = [
            {
                "role": "system",
                "content": f"You are chatting with {user}",
            },
            {
                "role": "system",
                "content": (
                    "You are a message classifier. You classify user messages and"
                    " return valid JSON based on your classification. In this instance"
                    " you are classifying messages based on whether they are related to"
                    " searching orders or not."
                ),
            },
            {
                "role": "system",
                "content": (
                    "The keys for the JSON object, when a user wants to search"
                    " published orders, are classification, subject, and event_type."
                ),
            },
            {
                "role": "system",
                "content": (
                    "There are two possible values for the classification key,"
                    " search_orders or null. search_orders is used when the user wants"
                    " to search the published orders, otherwise null is used."
                ),
            },
            {
                "role": "system",
                "content": (
                    "The value for the subject key is the name of the person for which"
                    " the user is searching for information. If the user references"
                    " themself, the subject would be their first and last name."
                ),
            },
            {
                "role": "system",
                "content": (
                    "The value for event_type is the type of data that the user is"
                    " interested in. Possible values are tos, sos, training,"
                    " course, embodied, disembodied, posted, appointed, allowance,"
                    " leave, short pass, exemption, marriage, awol, punishment, and"
                    " forfeiture."
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
