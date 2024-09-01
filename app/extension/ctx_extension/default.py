"""Provides an implementation of ICTXExtension."""

__all__ = ["DefaultCTXExtension"]

from datetime import datetime
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide

from app.core.contract.ctx_extension import ICTXExtension
from app.core.di import DIContainer


# pylint: disable=too-few-public-methods
class DefaultCTXExtension(ICTXExtension):
    """An implementation of ICTXExtension to provide default system context."""

    @inject
    def __init__(
        self,
        config: dict = Provide[DIContainer.config],
        user_service=Provide[DIContainer.user_service],
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._user_service = user_service

    def get_context(self, user: str) -> list[dict]:
        known_users_list = self._user_service.get_known_users_list()
        return [
            # Date and time.
            {
                "role": "system",
                "content": "The day of the week, date, and time are "
                + datetime.now().strftime("%A, %Y-%m-%d, %H:%M:%S")
                + ", respectively",
            },
            # User information.
            {
                "role": "system",
                "content": (
                    "You are chatting with"
                    f" {self._user_service.get_user_display_name(user)} ({user})."
                    " Refer to this user by their first name unless otherwise"
                    " instructed."
                ),
            },
            # Known users.
            {
                "role": "system",
                "content": "The list of known users on the platform are: "
                + ",".join(
                    [
                        known_users_list[k]["displayname"] + " (" + k + ")"
                        for (k, _) in known_users_list.items()
                    ]
                )
                + ".",
            },
            # Task based conversations.
            # pylint: disable=line-too-long
            {
                "role": "system",
                "content": """Your primary role is to help the user complete tasks. If the user sends you a new message that is not a follow-up to the previous task, the user's message asks a new question, requests a new action, or changes the topic, consider it an indicator of a new task. If you are uncertain whether the message indicates a new task or a continuation, treat it as a follow-up unless it clearly shifts the context.

Do not consider messages containing only a simple greeting, like "hello," or only a stop-word, such as "ok," an indicator of a new task, unless these types of messages are repeated multiple times consecutively. When you detect a new task, prefix your message with [task], skip a line, then add your response. The square brackets are important. Never use anything other than square brackets!

A task has ended if you've completed a requested action, answered a question not likely to have a follow-up message, or reached a natural conclusion to the task. A natural conclusion might include scenarios where the user does not respond for a certain period or the conversation reaches an endpoint based on typical conversation patterns. Also consider a task complete if the user thanks you, indicates that they no longer need assistance, or explicitly cancels the task. However, if the user thanks you but then immediately asks another question, consider it a continuation of the previous task unless the question introduces a new topic.

When you detect the end of a task, write your response, skip a line, and add [end-task]. Again, the square brackets are important! Under no circumstances should you use any other type of bracket or omit the square brackets when indicating tasks.
""",
            },
        ]
