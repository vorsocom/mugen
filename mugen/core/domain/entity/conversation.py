"""Domain entity for tenant/user conversation identity."""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ConversationEntity:
    """A validated conversation identity payload."""

    conversation_id: str
    owner_user_id: str

    @classmethod
    def build(cls, *, conversation_id: str, owner_user_id: str) -> "ConversationEntity":
        if not isinstance(conversation_id, str) or conversation_id.strip() == "":
            raise ValueError("conversation_id must be a non-empty string")
        if not isinstance(owner_user_id, str) or owner_user_id.strip() == "":
            raise ValueError("auth_user must be a non-empty string")

        return cls(
            conversation_id=conversation_id.strip(),
            owner_user_id=owner_user_id.strip(),
        )
