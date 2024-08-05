"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from datetime import datetime
import json
import pickle

from nio import AsyncClient
from nltk.stem.snowball import SnowballStemmer

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.messaging_service import IMessagingService
from app.contract.platform_gateway import IPlatformGateway

stemmer = SnowballStemmer("english")

class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    def __init__(
        self,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        knowledge_retrieval_gateway: IKnowledgeRetrievalGateway,
        platform_gateway: IPlatformGateway,
    ) -> None:
        self._client = client
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._knowledge_retrieval_gateway = knowledge_retrieval_gateway
        self._platform_gateway = platform_gateway

    async def handle_text_message(
        self,
        room_id: str,
        message_id: str,
        sender: str,
        content: str,
        chat_history_key: str,
        known_users_list_key: str,
    ) -> str:
        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self._client.room_read_markers(room_id, message_id, message_id)

        classification = await self._completion_gateway.classify_message(
            message=content,
            model=self._keyval_storage_gateway.get("groq_api_classification_model"),
        )

        knowledge_docs: list[str] = []
        if classification is not None:
            instruct = json.loads(classification)
            print(json.dumps(instruct, indent=4))
            match instruct["classification"]:
                case "search_orders":
                    hits = await self._knowledge_retrieval_gateway.search_similar(
                        "mil_orders",
                        f"{instruct["subject"]} {instruct["event_type"]}"
                    )
                    if len(hits) > 0:
                        print(len(hits))
                        hit_str = "In {0} Orders Serial {1} dated {2}, paragraph {3} states: {4}"
                        knowledge_docs = [
                            hit_str.format(
                                x.payload["type"],
                                x.payload["serial"],
                                x.payload["date"],
                                x.payload["paragraph"],
                                x.payload["data"]
                            )
                            for x in hits
                        ]

                case _:
                    pass
        print(knowledge_docs)
        chat_history = []
        if not self._keyval_storage_gateway.has_key(chat_history_key):
            chat_history.append(
                {
                    "role": "system",
                    "content": self._keyval_storage_gateway.get("matrix_agent_persona"),
                }
            )
            known_users_list = pickle.loads(
                self._keyval_storage_gateway.get(known_users_list_key, False)
            )
            sender_name = known_users_list[sender]["displayname"] + " (" + sender + ")"
            chat_history.append(
                {
                    "role": "system",
                    "content": "You are chatting with " + sender_name,
                }
            )
            chat_history.append(
                {
                    "role": "system",
                    "content": self.get_known_users_message(known_users_list_key),
                }
            )
        else:
            chat_history = pickle.loads(
                self._keyval_storage_gateway.get(chat_history_key, False)
            )

        # Update persona.
        persona = self._keyval_storage_gateway.get("matrix_agent_persona")
        if chat_history[0]["content"] != persona:
            chat_history[0]["content"] = persona

        # Send user message to assistant with history.
        user_message = {"role": "user", "content": content}
        chat_history.append(user_message)
        chat_completion = await self._completion_gateway.get_completion(
            context=chat_history
            + [  # Append date context.
                {
                    "role": "system",
                    "content": "The day of the week, date, and time are "
                    + datetime.now().strftime("%A, %Y-%m-%d, %H:%M:%S")
                    + ", respectively",
                },
                # Append info on tracked meetings
                {
                    "role": "system",
                    "content": self._completion_gateway.get_scheduled_meetings_data(
                        sender
                    ),
                },
                # Append RAG data
                {
                    "role": "system",
                    "content": " || ".join(knowledge_docs)
                },
                {
                    "role": "system",
                    "content": (
                        "When giving information from orders, always cite the serial,"
                        " paragraph number, and date of publication. Do not make up any"
                        " information. If you do not have any information, say so."
                    )
                }
            ],
            model=self._keyval_storage_gateway.get("groq_api_model"),
        )

        # Send assistant response to the user.
        agent_response = "Error" if chat_completion is None else chat_completion
        await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": agent_response,
            },
        )

        agent_message = {"role": "assistant", "content": agent_response}
        chat_history.append(agent_message)
        self._keyval_storage_gateway.put(chat_history_key, pickle.dumps(chat_history))

        return agent_response

    def get_known_users_message(self, known_users_list_key: str) -> str:
        """Get the system message that informs the agent of the known users."""
        known_users_list = pickle.loads(
            self._keyval_storage_gateway.get(known_users_list_key, False)
        )
        return (
            "The list of known users on the platform are: "
            + ",".join(
                [
                    known_users_list[k]["displayname"] + " (" + k + ")"
                    for (k, _) in known_users_list.items()
                ]
            )
            + "."
        )

    def update_known_users(self, known_users_list_key: str) -> None:
        """Update the list of users known to the assistant by updating the chat history of
        all rooms with a system message.
        """
        histories = [x for x in self._keyval_storage_gateway.keys() if "chat_history:" in x]

        if len(histories) == 0:
            return

        known_users_message = self.get_known_users_message(known_users_list_key)

        for storage_key in histories:
            history = list(pickle.loads(self._keyval_storage_gateway.get(storage_key, False)))
            history[2] = {"role": "system", "content": known_users_message}
            self._keyval_storage_gateway.put(storage_key, pickle.dumps(history))
